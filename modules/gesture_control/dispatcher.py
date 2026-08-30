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
    DEFAULT_TRACKING_ZONE,
    GESTURE_TRACKING_ZONE_KEY,
    HAND_WARMUP_FRAMES,
    PHYSICAL_MOUSE_OVERRIDE_SECONDS,
    PHYSICAL_MOUSE_THRESHOLD_PX,
    PINCH_DEBOUNCE_FRAMES,
    PINCH_RELEASE_MULT,
    PROCESSING_FPS,
    SWIPE_COOLDOWN_FRAMES,
    SWIPE_HISTORY_FRAMES,
    SWIPE_MAX_DY_RATIO,
    SWIPE_MIN_DX,
    SWIPE_OPEN_HAND_RATIO,
    ZOOM_COOLDOWN_FRAMES,
    ZOOM_DELTA_THRESHOLD,
)
from modules.gesture_control.cursor_controller import CursorController, map_hand_to_screen
from modules.gesture_control.cursor_zoom import cursor_zoom
from modules.gesture_control.events import GestureAnnouncement
from modules.gesture_control.gesture_recognizer import (
    hand_centre,
    pinch_ratio,
    swipe_direction,
    two_hand_spread_delta,
)
from modules.gesture_control.hand_tracker import HandTracker
from modules.gesture_control.overlay_state import overlay_state
from modules.user_profile import service_layer as profile_service_layer
from modules.user_profile.uow import ProfileUnitOfWork

logger = get_logger(__name__)


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

    # --- worker ---

    def _announce(self, message: str) -> None:
        try:
            asyncio.run(self._bus.publish(GestureAnnouncement(message=message)))
        except Exception:
            logger.exception("Failed to publish GestureAnnouncement")

    def _run(self) -> None:
        zone = _load_float(GESTURE_TRACKING_ZONE_KEY, DEFAULT_TRACKING_ZONE)
        min_alpha = calibration.load_min_alpha()
        deadzone_px = calibration.load_deadzone_px()

        try:
            tracker = HandTracker(min_alpha=min_alpha)
            tracker.open()
            cursor = CursorController()
        except Exception as exc:
            logger.exception("Gesture worker failed to start")
            self._last_error = str(exc)
            self._announce("Не удалось включить режим жестов: " + str(exc))
            self._thread = None
            overlay_state.set(active=False)
            return

        overlay_state.set(active=True)
        cursor_zoom.enlarge()
        px_per_norm = cursor.screen_size[0] / max(zone, 1e-6)
        # No forced calibration on first activation (the user found the
        # surprise prompt annoying, and an un-finished session used to
        # freeze the cursor). The stored / default values work out of the
        # box; calibration runs only when "Калибровка" asks for it.
        threshold = calibration.load_threshold()
        session: calibration.CalibrationSession | None = None
        if self._recalibrate:
            self._recalibrate = False
            session = calibration.CalibrationSession(px_per_norm=px_per_norm)
            self._drain_calibration_prompt(session)

        frame_interval = 1.0 / PROCESSING_FPS
        prev_spread: float | None = None
        zoom_cooldown = 0
        pinch_state = False
        pinch_streak = 0
        override_until = 0.0
        announced_ready = False
        hand_seen_streak = 0
        swipe_x: list[float] = []
        swipe_y: list[float] = []
        swipe_cooldown = 0

        try:
            while not self._stop_event.is_set():
                loop_start = time.monotonic()
                if self._recalibrate:  # button pressed while already active
                    self._recalibrate = False
                    session = calibration.CalibrationSession(px_per_norm=px_per_norm)
                    self._drain_calibration_prompt(session)

                result = tracker.read()
                if result is None:
                    self._stop_event.wait(frame_interval)
                    continue

                # The physical mouse always wins: if the OS cursor moved
                # away from where we left it, yield for a short cooldown.
                if cursor.physical_mouse_moved(PHYSICAL_MOUSE_THRESHOLD_PX):
                    override_until = loop_start + PHYSICAL_MOUSE_OVERRIDE_SECONDS
                    if pinch_state:
                        cursor.click_up()
                        pinch_state = False
                        pinch_streak = 0
                if loop_start < override_until:
                    if pinch_state:
                        cursor.click_up()
                        pinch_state = False
                    cursor.sync_last_set()
                    self._pace(loop_start, frame_interval)
                    continue

                if not result.hands:
                    if pinch_state:
                        cursor.click_up()
                        pinch_state = False
                    prev_spread = None
                    hand_seen_streak = 0
                    swipe_x.clear()
                    swipe_y.clear()
                    self._pace(loop_start, frame_interval)
                    continue

                primary = result.hands[0]
                ratio = pinch_ratio(primary)

                # A hand must persist a few frames before it drives the
                # cursor — a one-frame false positive (a passing object, the
                # user's head) can't jerk the pointer.
                hand_seen_streak += 1
                if session is None and hand_seen_streak < HAND_WARMUP_FRAMES:
                    cursor.sync_last_set()
                    self._pace(loop_start, frame_interval)
                    continue

                if session is not None and not session.done:
                    # Steady-phase tremor is measured on the *raw* fingertip —
                    # the smoothed one would understate the very shake we're
                    # trying to size the deadzone against.
                    session.observe(ratio, result.raw_primary_tip or primary[8])
                    self._drain_calibration_prompt(session)
                    if session.done:
                        threshold, deadzone_px, applied_alpha = session.persist()
                        tracker.set_min_alpha(applied_alpha)
                        session = None
                    self._pace(loop_start, frame_interval)
                    continue

                if not announced_ready:
                    announced_ready = True
                    self._announce(
                        "Режим жестов включён. Щипок — клик и перетаскивание, две руки — масштаб, "
                        "взмах открытой ладонью — переключение окон. Возьмётесь за мышь — жесты уступают."
                    )

                # Open-palm horizontal swipe -> Alt+Tab. Tracked on the palm
                # centre; suppressed while pinching so a drag isn't read as a
                # swipe, and the cooldown freezes the cursor so the swipe
                # itself doesn't fling the pointer across the screen.
                centre = hand_centre(primary)
                if pinch_state:
                    swipe_x.clear()
                    swipe_y.clear()
                else:
                    swipe_x.append(centre[0])
                    swipe_y.append(centre[1])
                    if len(swipe_x) > SWIPE_HISTORY_FRAMES:
                        swipe_x.pop(0)
                        swipe_y.pop(0)

                if swipe_cooldown > 0:
                    swipe_cooldown -= 1
                    cursor.sync_last_set()
                    self._pace(loop_start, frame_interval)
                    continue

                if not pinch_state and len(result.hands) == 1 and ratio > SWIPE_OPEN_HAND_RATIO:
                    direction = swipe_direction(
                        swipe_x, swipe_y, SWIPE_MIN_DX, SWIPE_MAX_DY_RATIO
                    )
                    if direction != 0:
                        cursor.trigger_window_switch("next" if direction > 0 else "prev")
                        swipe_cooldown = SWIPE_COOLDOWN_FRAMES
                        swipe_x.clear()
                        swipe_y.clear()
                        cursor.sync_last_set()
                        self._pace(loop_start, frame_interval)
                        continue

                target = map_hand_to_screen(primary[8], cursor.screen_size, zone)
                cx, cy = cursor.current_pos()
                if abs(target[0] - cx) >= deadzone_px or abs(target[1] - cy) >= deadzone_px:
                    cursor.move_cursor(*target)

                # Pinch with hysteresis (release at 1.5x the threshold) and
                # a 2-frame debounce so a click never flickers.
                exit_threshold = threshold * PINCH_RELEASE_MULT
                desired = ratio <= threshold if not pinch_state else ratio <= exit_threshold
                if desired != pinch_state:
                    pinch_streak += 1
                    if pinch_streak >= PINCH_DEBOUNCE_FRAMES:
                        pinch_state = desired
                        pinch_streak = 0
                        cursor.click_down() if pinch_state else cursor.click_up()
                else:
                    pinch_streak = 0

                if len(result.hands) >= 2:
                    prev_spread, delta = two_hand_spread_delta(
                        result.hands[0], result.hands[1], prev_spread
                    )
                    if zoom_cooldown > 0:
                        zoom_cooldown -= 1
                    elif delta > ZOOM_DELTA_THRESHOLD:
                        cursor.trigger_zoom("in")
                        zoom_cooldown = ZOOM_COOLDOWN_FRAMES
                    elif delta < -ZOOM_DELTA_THRESHOLD:
                        cursor.trigger_zoom("out")
                        zoom_cooldown = ZOOM_COOLDOWN_FRAMES
                else:
                    prev_spread = None

                self._pace(loop_start, frame_interval)
        except Exception:
            logger.exception("Gesture worker loop crashed")
            self._announce("Режим жестов остановлен из-за ошибки.")
        finally:
            cursor.release()
            tracker.close()
            cursor_zoom.restore()
            overlay_state.set(active=False)

    def _drain_calibration_prompt(self, session: calibration.CalibrationSession) -> None:
        message = session.take_announcement()
        if message:
            self._announce(message)

    def _pace(self, loop_start: float, frame_interval: float) -> None:
        remaining = frame_interval - (time.monotonic() - loop_start)
        if remaining > 0:
            self._stop_event.wait(remaining)


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
