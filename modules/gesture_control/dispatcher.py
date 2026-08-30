from __future__ import annotations

import asyncio
import math
import threading
import time
from typing import Any

from core.dispatcher import CommandDispatcher
from core.logger import get_logger
from core.message_bus import MessageBus, message_bus
from modules.gesture_control import calibration
from modules.gesture_control.config import (
    DEFAULT_TRACKING_ZONE,
    FIST_DEBOUNCE_FRAMES,
    FIST_LOST_GRACE_FRAMES,
    GESTURE_TRACKING_ZONE_KEY,
    HAND_WARMUP_FRAMES,
    PHYSICAL_MOUSE_OVERRIDE_SECONDS,
    PHYSICAL_MOUSE_THRESHOLD_PX,
    PROCESSING_FPS,
    SWIPE_COOLDOWN_FRAMES,
    SWIPE_HISTORY_FRAMES,
    SWIPE_MAX_DY_RATIO,
    SWIPE_OPEN_STREAK_FRAMES,
    ZOOM_COOLDOWN_FRAMES,
    ZOOM_DELTA_THRESHOLD,
)
from modules.gesture_control.cursor_controller import (
    CursorController,
    bounds_from_zone,
    map_hand_to_screen,
)
from modules.gesture_control.cursor_zoom import cursor_zoom
from modules.gesture_control.events import GestureAnnouncement
from modules.gesture_control.gesture_recognizer import (
    fist_score,
    hand_centre,
    is_open_palm,
    open_palm_score,
    swipe_direction,
    two_hand_spread_delta,
)
from modules.gesture_control.hand_tracker import HandTracker
from modules.gesture_control.one_euro_filter import OneEuroFilter
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
        # Optional diagnostic camera preview (§1). The worker only snapshots
        # the frame + landmarks while _preview_enabled; the drawing + JPEG
        # encode happen on demand in render_preview_jpeg(), off the hot path.
        self._preview_enabled = False
        self._preview_lock = threading.Lock()
        self._preview_source: tuple[object, list] | None = None

    # --- public API (called from command handlers / API) ---

    def is_active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def last_error(self) -> str | None:
        return self._last_error

    def set_preview_enabled(self, enabled: bool) -> None:
        self._preview_enabled = bool(enabled)
        if not enabled:
            with self._preview_lock:
                self._preview_source = None

    def render_preview_jpeg(self) -> bytes | None:
        if not self._preview_enabled:
            return None
        with self._preview_lock:
            source = self._preview_source
        if source is None:
            return None
        from modules.gesture_control import preview

        return preview.render_jpeg(source[0], source[1])

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
        bounds = calibration.load_zone_bounds() or bounds_from_zone(zone)
        deadzone_px = calibration.load_deadzone_px()
        fist_threshold = calibration.load_fist_threshold()
        open_palm_ratio = calibration.load_open_palm_ratio()
        swipe_min_dx = calibration.load_swipe_min_dx()
        euro = OneEuroFilter(min_cutoff=calibration.load_min_cutoff())

        try:
            tracker = HandTracker()
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
        px_per_norm = cursor.screen_size[0] / max(bounds[1] - bounds[0], 1e-6)

        session: calibration.CalibrationSession | None = None
        if self._recalibrate:
            self._recalibrate = False
            session = calibration.CalibrationSession(px_per_norm=px_per_norm)
            self._drain_calibration_prompt(session)
            overlay_state.set_calibration(session.progress())

        frame_interval = 1.0 / PROCESSING_FPS
        warmup_cap = HAND_WARMUP_FRAMES + 2
        seen = 0
        announced = False
        override_until = 0.0
        fist_held = False
        fist_streak = 0
        fist_lost = 0
        palm_streak = 0
        swipe_x: list[float] = []
        swipe_y: list[float] = []
        swipe_cooldown = 0
        prev_spread: float | None = None
        zoom_cooldown = 0

        def _release_click() -> None:
            nonlocal fist_held, fist_streak
            if fist_held:
                cursor.click_up()
            fist_held = False
            fist_streak = 0

        try:
            while not self._stop_event.is_set():
                loop_start = time.monotonic()
                if self._recalibrate:  # button pressed while already active
                    self._recalibrate = False
                    session = calibration.CalibrationSession(px_per_norm=px_per_norm)
                    self._drain_calibration_prompt(session)
                    overlay_state.set_calibration(session.progress())

                result = tracker.read()
                if result is None:
                    self._stop_event.wait(frame_interval)
                    continue

                if self._preview_enabled:
                    with self._preview_lock:
                        self._preview_source = (result.frame, [list(h) for h in result.hands])

                # Physical mouse always wins.
                if cursor.physical_mouse_moved(PHYSICAL_MOUSE_THRESHOLD_PX):
                    override_until = loop_start + PHYSICAL_MOUSE_OVERRIDE_SECONDS
                    _release_click()
                if loop_start < override_until:
                    _release_click()
                    cursor.sync_last_set()
                    euro.reset()
                    self._pace(loop_start, frame_interval)
                    continue

                hands = result.hands
                if not hands:
                    if fist_held and fist_lost < FIST_LOST_GRACE_FRAMES:
                        fist_lost += 1
                        self._pace(loop_start, frame_interval)
                        continue
                    _release_click()
                    seen = max(0, seen - 1)
                    euro.reset()
                    swipe_x.clear()
                    swipe_y.clear()
                    palm_streak = 0
                    prev_spread = None
                    self._pace(loop_start, frame_interval)
                    continue
                fist_lost = 0

                primary = hands[0]
                palm = hand_centre(primary)
                fist_s = fist_score(primary)
                palm_open_s = open_palm_score(primary)

                # --- calibration wizard ---
                if session is not None and not session.done:
                    session.observe(
                        calibration.CalibrationFrame(
                            fist_score=fist_s,
                            open_palm_score=palm_open_s,
                            raw_tip=palm,
                            palm_centre=palm,
                            brightness=result.brightness,
                        )
                    )
                    self._drain_calibration_prompt(session)
                    overlay_state.set_calibration(session.progress())
                    if session.done:
                        applied = session.persist()
                        if not session.aborted:
                            fist_threshold = applied.fist_threshold
                            deadzone_px = applied.deadzone_px
                            open_palm_ratio = applied.open_palm_ratio
                            swipe_min_dx = applied.swipe_min_dx
                            if applied.zone_bounds is not None:
                                bounds = applied.zone_bounds
                            euro.set_min_cutoff(applied.min_cutoff)
                        session = None
                        overlay_state.set_calibration(None)
                    self._pace(loop_start, frame_interval)
                    continue

                seen = min(seen + 1, warmup_cap)
                if seen < HAND_WARMUP_FRAMES:
                    cursor.sync_last_set()
                    self._pace(loop_start, frame_interval)
                    continue
                if not announced:
                    announced = True
                    self._announce("Режим жестов включён.")

                fist_now = fist_s <= fist_threshold

                # --- open-palm swipe = switch windows ---
                if not fist_now and not fist_held and is_open_palm(primary, open_palm_ratio):
                    palm_streak += 1
                else:
                    palm_streak = 0
                    swipe_x.clear()
                    swipe_y.clear()

                if swipe_cooldown > 0:
                    swipe_cooldown -= 1
                    cursor.sync_last_set()
                    self._pace(loop_start, frame_interval)
                    continue

                if palm_streak >= SWIPE_OPEN_STREAK_FRAMES:
                    swipe_x.append(palm[0])
                    swipe_y.append(palm[1])
                    if len(swipe_x) > SWIPE_HISTORY_FRAMES:
                        swipe_x.pop(0)
                        swipe_y.pop(0)
                    direction = swipe_direction(swipe_x, swipe_y, swipe_min_dx, SWIPE_MAX_DY_RATIO)
                    if direction != 0:
                        cursor.trigger_window_switch("next" if direction > 0 else "prev")
                        swipe_cooldown = SWIPE_COOLDOWN_FRAMES
                        swipe_x.clear()
                        swipe_y.clear()
                        palm_streak = 0
                    cursor.sync_last_set()
                    self._pace(loop_start, frame_interval)
                    continue

                # --- cursor: palm centre, One-Euro filtered, moved every tick ---
                fx, fy = euro.update(palm, loop_start)
                tx, ty = map_hand_to_screen((fx, fy), cursor.screen_size, bounds)
                cx, cy = cursor.current_pos()
                if abs(tx - cx) >= deadzone_px or abs(ty - cy) >= deadzone_px:
                    cursor.move_cursor(tx, ty)

                # --- fist = click / drag (simple debounce) ---
                if fist_now != fist_held:
                    fist_streak += 1
                    if fist_streak >= FIST_DEBOUNCE_FRAMES:
                        fist_held = fist_now
                        fist_streak = 0
                        cursor.click_down() if fist_held else cursor.click_up()
                else:
                    fist_streak = 0

                # --- two-hand spread = zoom ---
                if len(hands) >= 2:
                    prev_spread, delta = two_hand_spread_delta(hands[0], hands[1], prev_spread)
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
            # Each step guarded so a failure in one still runs the rest —
            # in particular cursor_zoom.restore() must always fire or the
            # desktop cursor stays enlarged.
            for cleanup in (
                cursor.release,
                tracker.close,
                cursor_zoom.restore,
                lambda: overlay_state.set(active=False),
            ):
                try:
                    cleanup()
                except Exception:
                    logger.exception("Gesture worker cleanup step failed")
            with self._preview_lock:
                self._preview_source = None

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
    return {"message": "Начинаю калибровку. Голос и экран проведут по каждому жесту — повторите каждый пять раз."}


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
        description="Пошаговый мастер калибровки жестов под текущего пользователя (режим жестов должен быть активен).",
    )
