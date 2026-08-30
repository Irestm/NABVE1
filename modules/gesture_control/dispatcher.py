from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

from core.dispatcher import CommandDispatcher
from core.logger import get_logger
from core.message_bus import MessageBus, message_bus
from modules.gesture_control import calibration
from modules.gesture_control.config import (
    DEFAULT_CURSOR_SCALE,
    DEFAULT_EMA_ALPHA,
    DEFAULT_TRACKING_ZONE,
    GESTURE_CURSOR_SCALE_KEY,
    GESTURE_EMA_ALPHA_KEY,
    GESTURE_PINCH_THRESHOLD_KEY,
    GESTURE_TRACKING_ZONE_KEY,
    PROCESSING_FPS,
)
from modules.gesture_control.cursor_controller import CursorController, map_hand_to_screen
from modules.gesture_control.events import GestureAnnouncement
from modules.gesture_control.gesture_recognizer import (
    is_pinching,
    pinch_distance,
    two_hand_spread_delta,
)
from modules.gesture_control.hand_tracker import HandTracker
from modules.gesture_control.overlay_state import overlay_state
from modules.user_profile import service_layer as profile_service_layer
from modules.user_profile.uow import ProfileUnitOfWork

logger = get_logger(__name__)

# Hands must move apart / together by at least this (normalized units)
# between frames to count as an intentional zoom gesture, and we wait this
# many frames between zoom nudges so one spread doesn't fire ten times.
_ZOOM_DELTA_THRESHOLD = 0.03
_ZOOM_COOLDOWN_FRAMES = 6


def _load_float(key: str, default: float) -> float:
    raw = profile_service_layer.get_fact(ProfileUnitOfWork(), key)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


class GestureController:
    """Owns the whole opt-in gesture mode: one background worker thread that
    reads the camera, tracks hands, and drives the system cursor. Completely
    independent of core/voice/pipeline.py — voice commands keep working
    while this is on (that's the point, vs discussion_mode). Nothing runs
    until start()."""

    def __init__(self, bus: MessageBus = message_bus) -> None:
        self._bus = bus
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._recalibrate = False
        self._latest_jpeg: bytes | None = None
        self._jpeg_lock = threading.Lock()
        self._last_error: str | None = None

    # --- public API (called from command handlers / API) ---

    def is_active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def last_error(self) -> str | None:
        return self._last_error

    def start(self) -> bool:
        with self._lock:
            if self.is_active():
                return False
            self._stop_event.clear()
            self._last_error = None
            self._thread = threading.Thread(target=self._run, name="gesture-worker", daemon=True)
            self._thread.start()
        return True

    def stop(self) -> bool:
        with self._lock:
            if not self.is_active():
                return False
            self._stop_event.set()
            thread = self._thread
        assert thread is not None
        thread.join(timeout=5)
        self._thread = None
        overlay_state.set(active=False)
        return True

    def request_recalibration(self) -> bool:
        if not self.is_active():
            return False
        self._recalibrate = True
        return True

    def latest_jpeg(self) -> bytes | None:
        with self._jpeg_lock:
            return self._latest_jpeg

    def set_cursor_scale(self, scale: float) -> float:
        clamped = max(1.0, min(2.5, scale))
        profile_service_layer.set_fact(ProfileUnitOfWork(), GESTURE_CURSOR_SCALE_KEY, f"{clamped:.2f}")
        overlay_state.set(scale=clamped)
        return clamped

    # --- worker ---

    def _announce(self, message: str) -> None:
        try:
            asyncio.run(self._bus.publish(GestureAnnouncement(message=message)))
        except Exception:
            logger.exception("Failed to publish GestureAnnouncement")

    def _run(self) -> None:
        ema_alpha = _load_float(GESTURE_EMA_ALPHA_KEY, DEFAULT_EMA_ALPHA)
        zone = _load_float(GESTURE_TRACKING_ZONE_KEY, DEFAULT_TRACKING_ZONE)
        scale = _load_float(GESTURE_CURSOR_SCALE_KEY, DEFAULT_CURSOR_SCALE)

        try:
            tracker = HandTracker(ema_alpha=ema_alpha)
            tracker.open()
            cursor = CursorController()
        except Exception as exc:
            logger.exception("Gesture worker failed to start")
            self._last_error = str(exc)
            self._announce("Не удалось включить режим жестов: " + str(exc))
            self._thread = None
            overlay_state.set(active=False)
            return

        overlay_state.set(active=True, scale=scale)

        threshold = calibration.load_threshold()
        never_calibrated = (
            profile_service_layer.get_fact(ProfileUnitOfWork(), GESTURE_PINCH_THRESHOLD_KEY) is None
        )
        calibrating = self._recalibrate or never_calibrated
        session = calibration.CalibrationSession() if calibrating else None
        if calibrating:
            self._recalibrate = False
            self._announce("Калибровка жестов: медленно сожмите и разожмите большой и указательный пальцы три раза.")

        frame_interval = 1.0 / PROCESSING_FPS
        prev_spread: float | None = None
        zoom_cooldown = 0
        announced_ready = False

        try:
            while not self._stop_event.is_set():
                loop_start = time.monotonic()
                result = tracker.read()
                if result is None:
                    self._stop_event.wait(frame_interval)
                    continue

                self._update_preview(cursor, tracker, result)

                if not result.hands:
                    cursor.click_up()
                    prev_spread = None
                    self._pace(loop_start, frame_interval)
                    continue

                primary = result.hands[0]
                distance = pinch_distance(primary)

                if session is not None and not session.done:
                    session.observe(distance)
                    if session.done:
                        threshold = session.persist()
                        session = None
                        self._announce("Калибровка завершена. Режим жестов активен.")
                    self._pace(loop_start, frame_interval)
                    continue

                if not announced_ready:
                    announced_ready = True
                    self._announce("Режим жестов включён. Голосовые команды продолжают работать.")

                target = map_hand_to_screen(primary[8], cursor.screen_size, zone)
                cursor.move_cursor(*target)

                if is_pinching(distance, threshold):
                    cursor.click_down()
                else:
                    cursor.click_up()

                if len(result.hands) >= 2:
                    prev_spread, delta = two_hand_spread_delta(
                        result.hands[0], result.hands[1], prev_spread
                    )
                    if zoom_cooldown > 0:
                        zoom_cooldown -= 1
                    elif delta > _ZOOM_DELTA_THRESHOLD:
                        cursor.trigger_zoom("in")
                        zoom_cooldown = _ZOOM_COOLDOWN_FRAMES
                    elif delta < -_ZOOM_DELTA_THRESHOLD:
                        cursor.trigger_zoom("out")
                        zoom_cooldown = _ZOOM_COOLDOWN_FRAMES
                else:
                    prev_spread = None

                self._pace(loop_start, frame_interval)
        except Exception:
            logger.exception("Gesture worker loop crashed")
            self._announce("Режим жестов остановлен из-за ошибки.")
        finally:
            cursor.release()
            tracker.close()
            overlay_state.set(active=False)
            with self._jpeg_lock:
                self._latest_jpeg = None

    def _pace(self, loop_start: float, frame_interval: float) -> None:
        remaining = frame_interval - (time.monotonic() - loop_start)
        if remaining > 0:
            self._stop_event.wait(remaining)

    def _update_preview(self, cursor: CursorController, tracker: HandTracker, result) -> None:
        try:
            import cv2  # type: ignore[import-untyped]

            frame = result.frame
            height, width = frame.shape[:2]
            for hand in result.hands:
                for x, y in hand:
                    cv2.circle(frame, (int(x * width), int(y * height)), 3, (0, 220, 255), -1)
            ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
            if ok:
                with self._jpeg_lock:
                    self._latest_jpeg = buffer.tobytes()
        except Exception:
            logger.debug("Preview frame encode failed", exc_info=True)


gesture_controller = GestureController()


# --- dispatcher commands ---


async def _handle_gesture_start(_params: dict[str, Any]) -> dict[str, Any]:
    started = await asyncio.to_thread(gesture_controller.start)
    if not started:
        return {"active": True, "message": "Режим жестов уже включён."}
    return {"active": True, "message": "Включаю режим жестов."}


async def _handle_gesture_stop(_params: dict[str, Any]) -> dict[str, Any]:
    stopped = await asyncio.to_thread(gesture_controller.stop)
    if not stopped:
        return {"active": False, "message": "Режим жестов и так выключен."}
    return {"active": False, "message": "Режим жестов выключен."}


async def _handle_gesture_calibrate(_params: dict[str, Any]) -> dict[str, Any]:
    if not gesture_controller.request_recalibration():
        raise RuntimeError("Сначала включите режим жестов — калибровка идёт при активной камере.")
    return {"message": "Начинаю калибровку жестов."}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "gesture_start",
        _handle_gesture_start,
        dangerous=False,
        description="Включить режим управления курсором жестами через веб-камеру (ресурсоёмкий, opt-in).",
    )
    dispatcher.register(
        "gesture_stop",
        _handle_gesture_stop,
        dangerous=False,
        description="Выключить режим жестов и освободить камеру.",
    )
    dispatcher.register(
        "gesture_calibrate",
        _handle_gesture_calibrate,
        dangerous=False,
        description="Перекалибровать порог 'щипка' под текущего пользователя (режим жестов должен быть активен).",
    )
