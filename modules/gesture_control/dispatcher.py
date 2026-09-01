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
    BONE_FIT_ENABLED,
    BONE_SCAN_FRAMES,
    CLICK_ENGAGE_FRAMES,
    CLICK_FREEZE_FRAMES,
    CLICK_MAX_HOLD_SECONDS,
    CLICK_MEDIAN_WINDOW,
    CLICK_RELEASE_FRAMES,
    CLICK_TAP_SECONDS,
    CLUTCH_BOX,
    CURSOR_SENSITIVITY,
    DEFAULT_TRACKING_ZONE,
    FIST_FALLBACK_RATIO,
    FIST_LOST_GRACE_FRAMES,
    FIST_RELEASE_GAP,
    FIST_SCORE_MAX,
    FIST_SCORE_MIN,
    GESTURE_CURSOR_MODE,
    GESTURE_DIAG,
    GESTURE_TRACK_POINT,
    GESTURE_TRACKING_ZONE_KEY,
    HAND_LOST_COAST_FRAMES,
    HAND_WARMUP_FRAMES,
    HULL_ENGAGE,
    HULL_RELEASE,
    HULL_SCORE_MAX,
    MAX_CURSOR_STEP_FRAC,
    MAX_CURSOR_STEP_PX,
    PINCH_ENGAGE,
    PINCH_RELEASE,
    PINCH_SCORE_MAX,
    PRECLICK_DELTA,
    PRECLICK_FREEZE_FRAMES,
    PHYSICAL_MOUSE_OVERRIDE_SECONDS,
    PHYSICAL_MOUSE_THRESHOLD_PX,
    PROCESSING_FPS,
    REL_ACCEL,
    REL_GAIN_PX,
    REL_PRECISION_GAIN,
    REL_SPEED_REF,
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
from modules.gesture_control.bone_fit import BoneModel
from modules.gesture_control.gesture_recognizer import (
    fist_score,
    hand_centre,
    hull_compactness,
    index_tip,
    is_open_palm,
    open_palm_score,
    pinch2_gap,
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


def _hand_span(hand: list[tuple[float, float]]) -> float:
    xs = [p[0] for p in hand]
    ys = [p[1] for p in hand]
    return max(max(xs) - min(xs), max(ys) - min(ys))


def _sq_dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _apply_sensitivity(
    bounds: tuple[float, float, float, float], sensitivity: float
) -> tuple[float, float, float, float]:
    """Scale the tracking rectangle about its centre by 1 / sensitivity —
    sensitivity < 1 widens it (a bigger hand move per screen distance)."""
    if abs(sensitivity - 1.0) < 1e-3:
        return bounds
    x0, x1, y0, y1 = bounds
    out = []
    for lo, hi in ((x0, x1), (y0, y1)):
        centre = (lo + hi) / 2
        half = (hi - lo) / 2 / sensitivity
        out.extend((max(0.0, centre - half), min(1.0, centre + half)))
    return (out[0], out[1], out[2], out[3])


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
        bounds = _apply_sensitivity(
            calibration.load_zone_bounds() or bounds_from_zone(zone), CURSOR_SENSITIVITY
        )
        deadzone_px = calibration.load_deadzone_px()
        fist_threshold = calibration.load_fist_threshold()  # swipe guard + calibration only
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
        relative = GESTURE_CURSOR_MODE != "absolute"
        track_index = GESTURE_TRACK_POINT != "palm"
        track_of = index_tip if track_index else hand_centre
        cursor_px, cursor_py = (float(v) for v in cursor.current_pos())
        logger.info(
            "Gesture cursor mode: %s, tracking %s",
            "relative" if relative else "absolute",
            "index tip" if track_index else "palm centre",
        )

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
        bones = BoneModel()
        bone_ready_logged = False
        # Three independent click state machines OR'd onto the one OS button.
        hull_on = False
        hull_engage_streak = 0
        hull_release_streak = 0
        hull_buf: list[float] = []
        pinch_on = False
        pinch_engage_streak = 0
        pinch_release_streak = 0
        pinch_buf: list[float] = []
        fist_on = False
        fist_engage_streak = 0
        fist_release_streak = 0
        fist_buf: list[float] = []
        click_down_t = 0.0
        fist_lost = 0
        hand_lost = 0
        click_freeze = 0
        preclick_freeze = 0
        hull_prev = pinch_prev = fist_prev = None  # for the pre-click "closing" test
        prev_filtered: tuple[float, float] | None = None
        prev_t = 0.0
        prev_primary: tuple[float, float] | None = None
        last_track: tuple[float, float] | None = None
        palm_streak = 0
        swipe_x: list[float] = []
        swipe_y: list[float] = []
        swipe_cooldown = 0
        prev_spread: float | None = None
        zoom_cooldown = 0

        # --- diagnostics, flushed to a few INFO lines every 2s. Verbose on
        # purpose: distances, per-tick cursor step (pre/post clamp), where the
        # hand roams in the frame, how deep past the clutch box it goes, and
        # a per-cause breakdown of what the cursor did each tick.
        screen_w, screen_h = cursor.screen_size
        diag_since = time.monotonic()
        diag_ticks = 0
        diag_fist: list[float] = []
        diag_pinch2: list[float] = []
        diag_hull: list[float] = []
        diag_speed: list[float] = []
        diag_dhx: list[float] = []
        diag_dhy: list[float] = []
        diag_hx: list[float] = []
        diag_hy: list[float] = []
        diag_step_raw: list[float] = []
        diag_step_out: list[float] = []
        diag_gain: list[float] = []
        diag_clutch_margin = 0.0
        diag_clamped = 0
        diag_phys = 0
        diag_n_clutch = 0
        diag_n_preclick = 0
        diag_n_clickfreeze = 0
        diag_n_moved = 0
        diag_travel = 0.0

        def _release_click() -> None:
            nonlocal hull_on, pinch_on, fist_on
            nonlocal hull_engage_streak, hull_release_streak
            nonlocal pinch_engage_streak, pinch_release_streak
            nonlocal fist_engage_streak, fist_release_streak
            if cursor.is_holding:
                cursor.click_up()
                logger.info("Gesture click: released (hand lost / mouse override)")
            hull_on = pinch_on = fist_on = False
            hull_engage_streak = hull_release_streak = 0
            pinch_engage_streak = pinch_release_streak = 0
            fist_engage_streak = fist_release_streak = 0

        max_step_px = min(MAX_CURSOR_STEP_FRAC * min(screen_w, screen_h), float(MAX_CURSOR_STEP_PX))

        def _drive_cursor(tx: float, ty: float) -> tuple[float, float]:
            """Move the cursor toward an absolute screen point: clamp the
            per-tick step so a bad frame can't fling it across the display,
            apply the deadzone, and re-anchor the physical-mouse reference
            every tick (even when we don't move). Returns the FLOAT target
            after clamping — the caller keeps that as its accumulator, so
            sub-pixel motion below the deadzone still adds up (needed for
            fine aiming in relative mode) instead of being discarded."""
            nonlocal diag_clamped, diag_n_moved, diag_travel
            cx, cy = cursor.current_pos()
            dx, dy = tx - cx, ty - cy
            dist = math.hypot(dx, dy)
            if GESTURE_DIAG:
                diag_step_raw.append(dist)
            if dist > max_step_px > 0:
                scale = max_step_px / dist
                tx, ty = cx + dx * scale, cy + dy * scale
                dx, dy = tx - cx, ty - cy
                if GESTURE_DIAG:
                    diag_clamped += 1
            dz = 1.0 if relative else float(deadzone_px)
            step = math.hypot(dx, dy)
            if GESTURE_DIAG:
                diag_step_out.append(step)
            if abs(dx) >= dz or abs(dy) >= dz:
                cursor.move_cursor(int(round(tx)), int(round(ty)))
                if GESTURE_DIAG:
                    diag_n_moved += 1
                    diag_travel += step
                return tx, ty
            cursor.sync_last_set()
            return (tx, ty) if relative else (float(cx), float(cy))

        try:
            while not self._stop_event.is_set():
                loop_start = time.monotonic()
                if GESTURE_DIAG and loop_start - diag_since >= 2.0:
                    elapsed = loop_start - diag_since
                    n = max(diag_ticks, 1)

                    def _rng(vals: list[float], fmt: str = ".3f") -> str:
                        if not vals:
                            return "n/a"
                        return f"{min(vals):{fmt}}..{max(vals):{fmt}} (avg {sum(vals) / len(vals):{fmt}})"

                    cxp, cyp = cursor.current_pos()
                    cx0, cx1, cy0, cy1 = CLUTCH_BOX
                    logger.info(
                        "Gesture cursor: at (%d,%d) on %dx%d | edge-dist L=%d R=%d T=%d B=%d | "
                        "travelled %d px over %.1fs | step-raw %s | step-applied %s | "
                        "clamp hit %d/%d ticks (cap %d px) | gain %s",
                        cxp, cyp, screen_w, screen_h,
                        cxp, screen_w - cxp, cyp, screen_h - cyp,
                        int(diag_travel), elapsed,
                        _rng(diag_step_raw, ".0f"), _rng(diag_step_out, ".0f"),
                        diag_clamped, diag_ticks, int(max_step_px), _rng(diag_gain, ".2f"),
                    )
                    logger.info(
                        "Gesture hand: pos x %s y %s | per-tick move x %s y %s | speed %s norm/s "
                        "| clutch box x[%.2f-%.2f] y[%.2f-%.2f], went %.3f past it | "
                        "ticks: moved %d%% clutch %d%% preclick %d%% clickfreeze %d%% | phys-yield %d | bones %s",
                        _rng(diag_hx), _rng(diag_hy),
                        _rng(diag_dhx, ".4f"), _rng(diag_dhy, ".4f"), _rng(diag_speed),
                        cx0, cx1, cy0, cy1, diag_clutch_margin,
                        100 * diag_n_moved // n, 100 * diag_n_clutch // n,
                        100 * diag_n_preclick // n, 100 * diag_n_clickfreeze // n,
                        diag_phys, "ready" if bones.ready else "scanning",
                    )
                    logger.info(
                        "Gesture click-signals: hull* %s (eng<=%.2f rel>=%.2f) | pinch %s "
                        "(eng<=%.2f rel>=%.2f) | fist %s (fb<=%.2f)",
                        _rng(diag_hull), HULL_ENGAGE, HULL_RELEASE,
                        _rng(diag_pinch2), PINCH_ENGAGE, PINCH_RELEASE,
                        _rng(diag_fist), FIST_FALLBACK_RATIO,
                    )
                    diag_since = loop_start
                    diag_ticks = 0
                    diag_fist = []
                    diag_pinch2 = []
                    diag_hull = []
                    diag_speed = []
                    diag_dhx = []
                    diag_dhy = []
                    diag_hx = []
                    diag_hy = []
                    diag_step_raw = []
                    diag_step_out = []
                    diag_gain = []
                    diag_clutch_margin = 0.0
                    diag_clamped = 0
                    diag_phys = 0
                    diag_n_clutch = 0
                    diag_n_preclick = 0
                    diag_n_clickfreeze = 0
                    diag_n_moved = 0
                    diag_travel = 0.0
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
                    diag_phys += 1
                    _release_click()
                if loop_start < override_until:
                    _release_click()
                    cursor.sync_last_set()
                    euro.reset()
                    prev_primary = None
                    last_track = None
                    prev_filtered = None
                    click_freeze = 0
                    preclick_freeze = 0
                    hull_prev = pinch_prev = fist_prev = None
                    cursor_px, cursor_py = (float(v) for v in cursor.current_pos())
                    self._pace(loop_start, frame_interval)
                    continue

                hands = result.hands
                if not hands:
                    hand_lost += 1
                    # Hand gone: freeze the cursor. Relative mode makes this
                    # safe — prev_filtered is dropped, so re-acquire produces
                    # no delta and the cursor never teleports.
                    cursor.sync_last_set()
                    cursor_px, cursor_py = (float(v) for v in cursor.current_pos())
                    prev_filtered = None
                    if cursor.is_holding and fist_lost < FIST_LOST_GRACE_FRAMES:
                        fist_lost += 1
                        self._pace(loop_start, frame_interval)
                        continue
                    if hand_lost <= HAND_LOST_COAST_FRAMES:
                        self._pace(loop_start, frame_interval)
                        continue
                    _release_click()
                    seen = max(0, seen - 1)
                    euro.reset()
                    last_track = None
                    prev_primary = None
                    click_freeze = 0
                    preclick_freeze = 0
                    hull_prev = pinch_prev = fist_prev = None
                    swipe_x.clear()
                    swipe_y.clear()
                    palm_streak = 0
                    prev_spread = None
                    self._pace(loop_start, frame_interval)
                    continue
                hand_lost = 0
                fist_lost = 0

                # Lock onto one hand across frames: the detection nearest to
                # last frame's primary, not just the leftmost — a second (or
                # phantom) hand appearing used to swap hands[0] and teleport
                # the cursor. On a fresh acquire, prefer the bigger blob.
                if prev_primary is not None:
                    anchor = prev_primary
                    primary = min(hands, key=lambda h: _sq_dist(hand_centre(h), anchor))
                elif len(hands) > 1:
                    primary = max(hands, key=_hand_span)
                else:
                    primary = hands[0]

                # --- per-user rigid-bone fit: learn this hand's bone lengths,
                # then snap every later frame so a jumped landmark can't
                # stretch its segment (kills signal spikes at the source).
                # Scan only on frames that are a plain open hand (no
                # calibration session, not a fist / pinch) so a closed pose
                # can't skew the learned lengths. ---
                pre_fist = fist_score(primary)
                pre_pinch = pinch2_gap(primary)
                if BONE_FIT_ENABLED:
                    if not bones.ready:
                        if session is None and pre_fist > 1.1 and pre_pinch > 0.5:
                            bones.observe(primary)
                        if bones.ready and not bone_ready_logged:
                            bone_ready_logged = True
                            logger.info(
                                "Gesture bone model: ready (scanned %d frames)", BONE_SCAN_FRAMES
                            )
                    else:
                        primary = bones.fit(primary)

                palm = prev_primary = hand_centre(primary)
                fist_s = min(FIST_SCORE_MAX, max(FIST_SCORE_MIN, fist_score(primary)))
                pinch_s = min(PINCH_SCORE_MAX, pinch2_gap(primary))
                hull_s = min(HULL_SCORE_MAX, hull_compactness(primary))  # primary click signal
                palm_open_s = open_palm_score(primary)
                if GESTURE_DIAG:
                    diag_fist.append(fist_s)
                    diag_pinch2.append(pinch_s)
                    diag_hull.append(hull_s)

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
                    cursor_px, cursor_py = (float(v) for v in cursor.current_pos())
                    prev_filtered = None
                    self._pace(loop_start, frame_interval)
                    continue
                if not announced:
                    announced = True
                    self._announce("Режим жестов включён.")

                fist_now = fist_s <= fist_threshold

                # --- open-palm swipe = switch windows ---
                if not fist_now and not cursor.is_holding and is_open_palm(primary, open_palm_ratio):
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

                # --- medians: the click decisions need a stable signal ---
                fist_buf.append(fist_s)
                if len(fist_buf) > CLICK_MEDIAN_WINDOW:
                    fist_buf.pop(0)
                fist_med = sorted(fist_buf)[len(fist_buf) // 2]
                pinch_buf.append(pinch_s)
                if len(pinch_buf) > CLICK_MEDIAN_WINDOW:
                    pinch_buf.pop(0)
                pinch_med = sorted(pinch_buf)[len(pinch_buf) // 2]
                hull_buf.append(hull_s)
                if len(hull_buf) > CLICK_MEDIAN_WINDOW:
                    hull_buf.pop(0)
                hull_med = sorted(hull_buf)[len(hull_buf) // 2]

                # --- pre-click freeze: any click signal dropping fast (hand
                # closing) freezes the cursor delta, so the fingertip's
                # closing arc can't drag the pointer off target. Directional
                # and well above jitter — plain aiming never trips it. ---
                closing = (
                    (hull_prev is not None and hull_prev - hull_med > PRECLICK_DELTA)
                    or (pinch_prev is not None and pinch_prev - pinch_med > PRECLICK_DELTA)
                    or (fist_prev is not None and fist_prev - fist_med > PRECLICK_DELTA)
                )
                hull_prev, pinch_prev, fist_prev = hull_med, pinch_med, fist_med
                if closing:
                    preclick_freeze = PRECLICK_FREEZE_FRAMES

                # --- cursor point + hand speed (from the filtered point) ---
                track = last_track = track_of(primary)
                filtered = euro.update(track, result.capture_t)
                now_t = result.capture_t
                if prev_filtered is not None and now_t > prev_t:
                    dt = now_t - prev_t
                    d_hand = (filtered[0] - prev_filtered[0], filtered[1] - prev_filtered[1])
                    hand_speed = math.hypot(*d_hand) / dt
                else:
                    d_hand, hand_speed = (0.0, 0.0), 0.0
                prev_filtered, prev_t = filtered, now_t

                # --- clutch: hand outside the comfort box -> freeze, keep
                # tracking, so you can drop / recenter your arm ---
                cx0, cx1, cy0, cy1 = CLUTCH_BOX
                clutched = not (cx0 <= filtered[0] <= cx1 and cy0 <= filtered[1] <= cy1)

                if click_freeze > 0:
                    click_freeze -= 1
                if preclick_freeze > 0:
                    preclick_freeze -= 1

                gain = 0.0
                if GESTURE_DIAG:
                    diag_ticks += 1
                    diag_speed.append(hand_speed)
                    diag_hx.append(filtered[0])
                    diag_hy.append(filtered[1])
                    diag_dhx.append(d_hand[0])
                    diag_dhy.append(d_hand[1])
                    if clutched:
                        diag_n_clutch += 1
                        over = max(
                            cx0 - filtered[0], filtered[0] - cx1,
                            cy0 - filtered[1], filtered[1] - cy1, 0.0,
                        )
                        diag_clutch_margin = max(diag_clutch_margin, over)
                    if preclick_freeze > 0:
                        diag_n_preclick += 1
                    if click_freeze > 0:
                        diag_n_clickfreeze += 1

                # The cursor never force-stops on its own (a dwell freeze
                # locked it mid-aim). It holds only during a click freeze, a
                # pre-click freeze, or a clutch; otherwise it moves, with a
                # speed-shaped gain — fine when slow, accelerated when flicked.
                if click_freeze > 0 or preclick_freeze > 0 or clutched:
                    cursor.sync_last_set()
                    cursor_px, cursor_py = (float(v) for v in cursor.current_pos())
                elif relative:
                    norm = min(hand_speed / REL_SPEED_REF, 1.0)
                    precision = REL_PRECISION_GAIN + (1.0 - REL_PRECISION_GAIN) * norm
                    flick = 1.0 + REL_ACCEL * max(hand_speed - REL_SPEED_REF, 0.0) / REL_SPEED_REF
                    gain = REL_GAIN_PX * precision * flick
                    if GESTURE_DIAG:
                        diag_gain.append(gain)
                    nx = min(max(cursor_px + d_hand[0] * gain, 0.0), screen_w - 1.0)
                    ny = min(max(cursor_py + d_hand[1] * gain, 0.0), screen_h - 1.0)
                    cursor_px, cursor_py = _drive_cursor(nx, ny)
                else:
                    tx, ty = map_hand_to_screen(filtered, cursor.screen_size, bounds)
                    cursor_px, cursor_py = _drive_cursor(tx, ty)

                # --- click: HULL compactness (primary), PINCH, DEEP FIST —
                # three independent catch-fast / release-slow state machines
                # OR'd onto the one OS button, with a tap timeout + hard
                # max-hold so it can never stay stuck ---
                if not hull_on:
                    hull_engage_streak = (
                        hull_engage_streak + 1 if hull_med <= HULL_ENGAGE else 0
                    )
                    if hull_engage_streak >= CLICK_ENGAGE_FRAMES:
                        hull_on, hull_engage_streak = True, 0
                else:
                    hull_release_streak = (
                        hull_release_streak + 1 if hull_med >= HULL_RELEASE else 0
                    )
                    if hull_release_streak >= CLICK_RELEASE_FRAMES:
                        hull_on, hull_release_streak = False, 0

                if not pinch_on:
                    pinch_engage_streak = (
                        pinch_engage_streak + 1 if pinch_med <= PINCH_ENGAGE else 0
                    )
                    if pinch_engage_streak >= CLICK_ENGAGE_FRAMES:
                        pinch_on, pinch_engage_streak = True, 0
                else:
                    pinch_release_streak = (
                        pinch_release_streak + 1 if pinch_med >= PINCH_RELEASE else 0
                    )
                    if pinch_release_streak >= CLICK_RELEASE_FRAMES:
                        pinch_on, pinch_release_streak = False, 0

                if not fist_on:
                    fist_engage_streak = (
                        fist_engage_streak + 1 if fist_med <= FIST_FALLBACK_RATIO else 0
                    )
                    if fist_engage_streak >= CLICK_ENGAGE_FRAMES:
                        fist_on, fist_engage_streak = True, 0
                else:
                    fist_release_streak = (
                        fist_release_streak + 1
                        if fist_med >= FIST_FALLBACK_RATIO + FIST_RELEASE_GAP
                        else 0
                    )
                    if fist_release_streak >= CLICK_RELEASE_FRAMES:
                        fist_on, fist_release_streak = False, 0

                want_click = hull_on or pinch_on or fist_on
                held = cursor.is_holding
                still_squeezed = (
                    hull_med <= HULL_ENGAGE
                    or pinch_med <= PINCH_ENGAGE
                    or fist_med <= FIST_FALLBACK_RATIO
                )
                held_for = loop_start - click_down_t
                # A click is a tap by default: once it's been down a moment
                # and no signal is still actively squeezed, end it — don't
                # wait for the absolute release bars, which sit in this
                # user's relaxed-hand noise.
                tap_done = held and held_for > CLICK_TAP_SECONDS and not still_squeezed
                sig = "hull" if hull_on else "pinch" if pinch_on else "fist"
                if want_click and not held:
                    cursor.click_down()
                    click_down_t = loop_start
                    click_freeze = CLICK_FREEZE_FRAMES
                    logger.info(
                        "Gesture click: down via %s (hull=%.3f pinch=%.3f fist=%.2f)",
                        sig, hull_med, pinch_med, fist_med,
                    )
                elif held and (not want_click or tap_done):
                    cursor.click_up()
                    hull_on = pinch_on = fist_on = False
                    hull_release_streak = pinch_release_streak = fist_release_streak = 0
                    logger.info(
                        "Gesture click: up after %.2fs%s (hull=%.3f pinch=%.3f fist=%.2f)",
                        held_for, " [tap]" if tap_done and want_click else "",
                        hull_med, pinch_med, fist_med,
                    )
                elif held and held_for > CLICK_MAX_HOLD_SECONDS:
                    cursor.click_up()
                    hull_on = pinch_on = fist_on = False
                    hull_release_streak = pinch_release_streak = fist_release_streak = 0
                    logger.warning(
                        "Gesture click: force-released after %.1fs (hull=%.3f pinch=%.3f fist=%.2f)",
                        held_for, hull_med, pinch_med, fist_med,
                    )

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
