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
    DWELL_BREAK_PX,
    DWELL_FRAMES,
    DWELL_RADIUS_PX,
    GESTURE_TRACKING_ZONE_KEY,
    HAND_WARMUP_FRAMES,
    PHYSICAL_MOUSE_OVERRIDE_SECONDS,
    PHYSICAL_MOUSE_THRESHOLD_PX,
    PINCH_ENGAGE_DEBOUNCE_FRAMES,
    PINCH_LOST_GRACE_FRAMES,
    PINCH_RATIO_MEDIAN,
    PINCH_RELEASE_DEBOUNCE_FRAMES,
    PINCH_RELEASE_MULT,
    PRECISION_GAIN_MIN,
    PRECISION_SPEED_HIGH,
    PRECISION_SPEED_LOW,
    PROCESSING_FPS,
    SWIPE_COOLDOWN_FRAMES,
    SWIPE_HISTORY_FRAMES,
    SWIPE_MAX_DY_RATIO,
    SWIPE_OPEN_STREAK_FRAMES,
    ZOOM_COOLDOWN_FRAMES,
    ZOOM_DELTA_THRESHOLD,
)
from modules.gesture_control.cursor_controller import CursorController, map_hand_to_screen
from modules.gesture_control.cursor_zoom import cursor_zoom
from modules.gesture_control.events import GestureAnnouncement
from modules.gesture_control.gesture_recognizer import (
    hand_centre,
    is_open_palm,
    median,
    open_palm_score,
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


def _precision_gain(hand_speed: float) -> float:
    """Easing factor for the cursor's step toward the mapped hand position:
    PRECISION_GAIN_MIN when the hand is nearly still (fine aiming), rising to
    1.0 once it moves fast enough to cross the screen."""
    span = max(PRECISION_SPEED_HIGH - PRECISION_SPEED_LOW, 1e-6)
    t = max(0.0, min(1.0, (hand_speed - PRECISION_SPEED_LOW) / span))
    return PRECISION_GAIN_MIN + (1.0 - PRECISION_GAIN_MIN) * t


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
        open_palm_ratio = calibration.load_open_palm_ratio()
        swipe_min_dx = calibration.load_swipe_min_dx()

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
        warmup_cap = HAND_WARMUP_FRAMES + 2
        prev_spread: float | None = None
        zoom_cooldown = 0
        pinch_state = False
        pinch_streak = 0
        pinch_lost_grace = 0
        ratio_buf: list[float] = []
        override_until = 0.0
        announced_ready = False
        hand_seen_streak = 0
        swipe_x: list[float] = []
        swipe_y: list[float] = []
        swipe_cooldown = 0
        open_palm_streak = 0
        prev_tip: tuple[float, float] | None = None
        dwell_anchor: tuple[float, float] | None = None
        dwell_frames = 0

        def _release_pinch() -> None:
            nonlocal pinch_state, pinch_streak
            if pinch_state:
                cursor.click_up()
            pinch_state = False
            pinch_streak = 0

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
                    _release_pinch()
                if loop_start < override_until:
                    _release_pinch()
                    cursor.sync_last_set()
                    prev_tip = None
                    dwell_anchor = None
                    dwell_frames = 0
                    self._pace(loop_start, frame_interval)
                    continue

                if not result.hands:
                    # A pinch often makes MediaPipe drop the hand for a frame
                    # or two (thumb and index tips occlude) — hold the click
                    # through a short gap instead of releasing it.
                    if pinch_state and pinch_lost_grace < PINCH_LOST_GRACE_FRAMES:
                        pinch_lost_grace += 1
                        prev_spread = None
                        self._pace(loop_start, frame_interval)
                        continue
                    _release_pinch()
                    prev_spread = None
                    # decay, don't reset — a one-frame tracking gap shouldn't
                    # restart the warmup.
                    hand_seen_streak = max(0, hand_seen_streak - 1)
                    ratio_buf.clear()
                    swipe_x.clear()
                    swipe_y.clear()
                    open_palm_streak = 0
                    prev_tip = None
                    dwell_anchor = None
                    dwell_frames = 0
                    self._pace(loop_start, frame_interval)
                    continue

                pinch_lost_grace = 0

                primary = result.hands[0]
                tip = primary[8]
                raw_tip = result.raw_primary_tip or tip
                ratio_raw = pinch_ratio(primary)

                if session is not None and not session.done:
                    session.observe(
                        calibration.CalibrationFrame(
                            pinch_ratio=ratio_raw,
                            open_palm_score=open_palm_score(primary),
                            raw_tip=raw_tip,
                            palm_centre=hand_centre(primary),
                        )
                    )
                    self._drain_calibration_prompt(session)
                    if session.done:
                        applied = session.persist()
                        threshold = applied.pinch_threshold
                        deadzone_px = applied.deadzone_px
                        open_palm_ratio = applied.open_palm_ratio
                        swipe_min_dx = applied.swipe_min_dx
                        tracker.set_min_alpha(applied.min_alpha)
                        session = None
                    self._pace(loop_start, frame_interval)
                    continue

                hand_seen_streak = min(hand_seen_streak + 1, warmup_cap)
                if hand_seen_streak < HAND_WARMUP_FRAMES:
                    cursor.sync_last_set()
                    prev_tip = tip
                    self._pace(loop_start, frame_interval)
                    continue

                if not announced_ready:
                    announced_ready = True
                    self._announce("Режим жестов включён.")

                # "Catch fast, release slow": engage on the best (min) of the
                # last few raw ratios, release only when the median has
                # clearly climbed back. Landmark noise + the tip occlusion of
                # a real pinch made a stricter test miss most clicks.
                ratio_buf.append(ratio_raw)
                if len(ratio_buf) > PINCH_RATIO_MEDIAN:
                    ratio_buf.pop(0)
                release_threshold = threshold * PINCH_RELEASE_MULT
                if pinch_state:
                    pinching_now = median(ratio_buf) <= release_threshold
                else:
                    pinching_now = min(ratio_buf) <= threshold

                # --- swipe mode: a whole open palm, not pinching ---
                if not pinching_now and not pinch_state and is_open_palm(primary, open_palm_ratio):
                    open_palm_streak += 1
                else:
                    open_palm_streak = 0
                    swipe_x.clear()
                    swipe_y.clear()

                if swipe_cooldown > 0:
                    swipe_cooldown -= 1
                    cursor.sync_last_set()
                    prev_tip = tip
                    self._pace(loop_start, frame_interval)
                    continue

                if open_palm_streak >= SWIPE_OPEN_STREAK_FRAMES:
                    centre = hand_centre(primary)
                    swipe_x.append(centre[0])
                    swipe_y.append(centre[1])
                    if len(swipe_x) > SWIPE_HISTORY_FRAMES:
                        swipe_x.pop(0)
                        swipe_y.pop(0)
                    direction = swipe_direction(swipe_x, swipe_y, swipe_min_dx, SWIPE_MAX_DY_RATIO)
                    if direction != 0:
                        cursor.trigger_window_switch("next" if direction > 0 else "prev")
                        swipe_cooldown = SWIPE_COOLDOWN_FRAMES
                        swipe_x.clear()
                        swipe_y.clear()
                        open_palm_streak = 0
                    cursor.sync_last_set()
                    prev_tip = tip
                    dwell_anchor = None
                    dwell_frames = 0
                    self._pace(loop_start, frame_interval)
                    continue

                # --- pointing mode: cursor + pinch + two-hand zoom ---
                if prev_tip is None:
                    prev_tip = tip
                hand_speed = math.hypot(tip[0] - prev_tip[0], tip[1] - prev_tip[1])
                prev_tip = tip

                target = map_hand_to_screen(tip, cursor.screen_size, zone)
                cx, cy = cursor.current_pos()
                gain = _precision_gain(hand_speed)
                eased = (cx + (target[0] - cx) * gain, cy + (target[1] - cy) * gain)

                if dwell_anchor is None or math.hypot(
                    eased[0] - dwell_anchor[0], eased[1] - dwell_anchor[1]
                ) > DWELL_RADIUS_PX:
                    dwell_anchor = eased
                    dwell_frames = 0
                else:
                    dwell_frames += 1

                frozen = dwell_frames >= DWELL_FRAMES and math.hypot(
                    target[0] - dwell_anchor[0], target[1] - dwell_anchor[1]
                ) <= DWELL_BREAK_PX
                if not frozen:
                    ex, ey = int(round(eased[0])), int(round(eased[1]))
                    if abs(ex - cx) >= deadzone_px or abs(ey - cy) >= deadzone_px:
                        cursor.move_cursor(ex, ey)

                # Pinch: near-instant engage, debounced + hysteresis release
                # so a drag never drops on one bad frame.
                if pinching_now != pinch_state:
                    pinch_streak += 1
                    need = (
                        PINCH_ENGAGE_DEBOUNCE_FRAMES
                        if pinching_now
                        else PINCH_RELEASE_DEBOUNCE_FRAMES
                    )
                    if pinch_streak >= need:
                        pinch_state = pinching_now
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
    return {"message": "Начинаю калибровку. Голос проведёт по каждому жесту — повторите каждый три раза."}


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
