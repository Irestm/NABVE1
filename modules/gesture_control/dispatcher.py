from __future__ import annotations

import asyncio
import math
import queue
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
    CLICK_GAP_MAX,
    CLICK_MAX_HOLD_SECONDS,
    CLICK_MEDIAN_WINDOW,
    CLICK_RELEASE_FRAMES,
    CLICK_REPEAT_LOCKOUT_S,
    CLICK_TAP_SECONDS,
    CLICK_USE_HULL,
    DEFAULT_TRACKING_ZONE,
    FIST_FALLBACK_RATIO,
    FIST_LOST_GRACE_FRAMES,
    FIST_RELEASE_GAP,
    FIST_SCORE_MAX,
    FIST_SCORE_MIN,
    GESTURE_DIAG,
    HAND_LOST_COAST_FRAMES,
    HAND_WARMUP_FRAMES,
    HULL_ENGAGE,
    HULL_RELEASE,
    HULL_SCORE_MAX,
    ABS_FOLLOW_RATE,
    MAX_CURSOR_STEP_FRAC,
    MAX_CURSOR_STEP_PX,
    MIDDLE_DOWN_MAX,
    MOVE_FINGER_RATIO,
    PHYSICAL_MOUSE_OVERRIDE_SECONDS,
    PHYSICAL_MOUSE_THRESHOLD_PX,
    PRECLICK_DELTA,
    PRECLICK_FREEZE_FRAMES,
    PROCESSING_FPS,
    RIGHT_AFTER_LEFT_LOCKOUT_S,
    RIGHT_CLICK_FRAMES,
    RIGHT_CLICK_LOCKOUT_S,
    SCROLL_DEADZONE_NORM,
    SCROLL_ENTER_FRAMES,
    SCROLL_EXIT_FRAMES,
    SCROLL_INVERT,
    SCROLL_MAX_CLICKS_PER_TICK,
    SCROLL_MID_WINDOW,
    SCROLL_MIDDLE_MIN,
    SCROLL_MIDDLE_STAY,
    SCROLL_STEP_NORM,
    THUMB_GAP_MIN,
    THUMB_TUCKED_MAX,
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
    finger_straightness,
    hand_centre,
    hull_compactness,
    index_middle_gap,
    index_tip,
    thumb_gap,
)
from modules.gesture_control.hand_tracker import CameraUnavailable, HandTracker
from modules.gesture_control.one_euro_filter import OneEuroFilter
from modules.gesture_control.overlay_state import overlay_state

logger = get_logger(__name__)

# How long stop() waits for the worker thread to finish. If it overruns
# (a wedged camera release / a hung gsettings), stop() reports failure and
# — crucially — does NOT clear the thread handle, so a follow-up start()
# can't spawn a second worker on top of the one still shutting down.
# Module-level so tests can shrink it.
_STOP_JOIN_TIMEOUT_S = 8.0


def _hand_span(hand: list[tuple[float, float]]) -> float:
    xs = [p[0] for p in hand]
    ys = [p[1] for p in hand]
    return max(max(xs) - min(xs), max(ys) - min(ys))


def _sq_dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


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
        # The main asyncio loop (bound at backend startup). Spoken feedback is
        # published onto it, off the worker's hot path — see _announce.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._announce_q: queue.Queue[str] = queue.Queue()
        self._announce_lock = threading.Lock()
        self._announce_thread: threading.Thread | None = None
        # Set by the worker itself the instant its _run() returns (any path:
        # clean stop, camera fault, crash). is_active() consults it so the
        # window between "worker finished" and "OS thread actually exited"
        # doesn't read as still-active. Only stop()/start() touch _thread.
        self._worker_done = threading.Event()
        self._recalibrate = False
        self._cancel_calibration = False
        self._last_error: str | None = None
        # Optional diagnostic camera preview (§1). The worker only snapshots
        # the frame + landmarks while _preview_enabled; the drawing + JPEG
        # encode happen on demand in render_preview_jpeg(), off the hot path.
        self._preview_enabled = False
        self._preview_lock = threading.Lock()
        self._preview_source: tuple[object, list] | None = None

    # --- public API (called from command handlers / API) ---

    def is_active(self) -> bool:
        thread = self._thread
        return (
            thread is not None
            and thread.is_alive()
            and not self._worker_done.is_set()
        )

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
            # is_active() stays True for a worker that's alive but wedged in
            # shutdown (a stop() whose join timed out), so this also blocks
            # starting a second worker over one that won't die.
            if self.is_active():
                return False
            self._stop_event.clear()
            self._worker_done.clear()
            self._recalibrate = False
            self._cancel_calibration = False
            self._last_error = None
            self._thread = threading.Thread(target=self._run, name="gesture-worker", daemon=True)
            self._thread.start()
        return True

    def stop(self) -> bool:
        with self._lock:
            thread = self._thread
            if thread is None or not thread.is_alive():
                # Nothing running, or the worker already self-terminated
                # (camera fault / crash) — reap the handle and report "off".
                self._thread = None
                overlay_state.set(active=False)
                return False
            self._stop_event.set()
        thread.join(timeout=_STOP_JOIN_TIMEOUT_S)
        if thread.is_alive():
            logger.warning(
                "Gesture worker did not stop within %.0fs — keeping the handle so a "
                "restart can't spawn a second worker over it",
                _STOP_JOIN_TIMEOUT_S,
            )
            self._last_error = "Не удалось остановить режим жестов вовремя — попробуйте ещё раз."
            return False
        with self._lock:
            self._thread = None
        overlay_state.set(active=False)
        return True

    def request_recalibration(self) -> bool:
        if not self.is_active():
            return False
        self._recalibrate = True
        return True

    def cancel_calibration(self) -> bool:
        if not self.is_active():
            return False
        self._cancel_calibration = True
        return True

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called once at backend startup so _announce can hand spoken
        feedback to the running app loop instead of spinning its own."""
        self._loop = loop

    # --- worker ---

    def _announce(self, message: str) -> None:
        """Enqueue spoken feedback and return immediately — the worker loop
        must never block for the length of a TTS utterance. A lazily-started
        daemon drains the queue one message at a time (so prompts don't
        overlap) and publishes each onto the bound app loop."""
        with self._announce_lock:
            if self._announce_thread is None or not self._announce_thread.is_alive():
                self._announce_thread = threading.Thread(
                    target=self._announce_pump, name="gesture-announce", daemon=True
                )
                self._announce_thread.start()
        self._announce_q.put(message)

    def _announce_pump(self) -> None:
        while True:
            message = self._announce_q.get()
            event = GestureAnnouncement(message=message)
            loop = self._loop
            try:
                if loop is not None and loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(self._bus.publish(event), loop)
                    future.result(timeout=30)
                else:
                    asyncio.run(self._bus.publish(event))
            except Exception:
                logger.exception("Failed to publish GestureAnnouncement")

    def _run(self) -> None:
        # Personal values from the calibration wizard — all applied below.
        min_cutoff = calibration.load_min_cutoff()
        deadzone_px = calibration.load_deadzone_px()
        zone_bounds = calibration.load_zone_bounds()
        click_gap_eng, click_gap_rel = calibration.load_click_gap_thresholds()
        euro = OneEuroFilter(min_cutoff=min_cutoff)

        try:
            tracker = HandTracker()
            tracker.open()
            cursor = CursorController()
        except Exception as exc:
            logger.exception("Gesture worker failed to start")
            self._last_error = str(exc)
            self._announce("Не удалось включить режим жестов: " + str(exc))
            overlay_state.set(active=False)
            self._worker_done.set()
            return

        # active + enlarged cursor are deferred to the first real frame
        # (see `activated` below): if the camera opens but never delivers
        # (busy elsewhere), /api/status must not report the mode as active.
        activated = False
        # ABSOLUTE mapping: a rectangle in the (mirrored) frame -> the whole
        # screen. Point the index fingertip near a frame corner and the
        # cursor is at that screen corner. The cursor is only driven while
        # the hand is in the two-finger "pointing" pose — any other pose
        # (fist, one finger, hand dropped) holds the cursor, which is the
        # clutch: make a fist to reposition your arm.
        bounds = zone_bounds or bounds_from_zone(DEFAULT_TRACKING_ZONE)
        screen_w, screen_h = cursor.screen_size
        px_per_norm = screen_w / max(bounds[1] - bounds[0], 1e-6)
        cursor_px, cursor_py = (float(v) for v in cursor.current_pos())
        logger.info(
            "Gesture: absolute + finger-state | zone %s%s | click-gap %.2f/%.2f | "
            "deadzone %dpx cutoff %.2f",
            tuple(round(b, 2) for b in bounds), " (calibrated)" if zone_bounds else "",
            click_gap_eng, click_gap_rel, deadzone_px, min_cutoff,
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
        # LEFT click state machines OR'd onto the one OS button: `pinch_*`
        # now tracks the index<->middle FINGERTIP GAP (small = tips together
        # = click), `fist_*` the full-fist fallback, `hull_*` the opt-in.
        hull_on = False
        hull_engage_streak = 0
        hull_release_streak = 0
        hull_buf: list[float] = []
        pinch_on = False
        click_gap_engage_streak = 0
        click_gap_release_streak = 0
        pinch_buf: list[float] = []
        fist_on = False
        fist_engage_streak = 0
        fist_release_streak = 0
        fist_buf: list[float] = []
        click_down_t = 0.0
        click_lock_until = 0.0
        click_held_through = False  # hand hasn't clearly opened since the last click
        open_streak = 0  # consecutive frames the hand has been clearly open
        hand_lost = 0
        click_freeze = 0
        preclick_freeze = 0
        hull_prev = pinch_prev = fist_prev = None  # for the pre-click "closing" test
        right_streak = 0        # ring-folded frames toward a right click
        right_lock_until = 0.0  # right-click fired -> locked until this time / ring extends
        # scroll pose: index + middle both up, vertical fingertip travel -> wheel
        scroll_on = False
        scroll_enter_streak = 0
        scroll_exit_streak = 0
        scroll_anchor_y: float | None = None
        scroll_accum = 0.0
        mid_buf: list[float] = []
        open_palm_streak = 0    # index up + thumb spread = "do nothing, repositioning"
        prev_filtered: tuple[float, float] | None = None
        prev_t = 0.0
        prev_primary: tuple[float, float] | None = None

        # --- diagnostics, flushed to a few INFO lines every 2s.
        diag_since = time.monotonic()
        diag_ticks = 0
        diag_fist: list[float] = []
        diag_pinch2: list[float] = []
        diag_hull: list[float] = []
        diag_idx: list[float] = []
        diag_mid: list[float] = []
        diag_ring: list[float] = []
        diag_pnk: list[float] = []
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
        diag_n_arm = 0
        diag_n_open = 0
        diag_n_preclick = 0
        diag_n_clickfreeze = 0
        diag_n_moved = 0
        diag_travel = 0.0

        def _release_click() -> None:
            nonlocal hull_on, pinch_on, fist_on, click_held_through
            nonlocal hull_engage_streak, hull_release_streak
            nonlocal click_gap_engage_streak, click_gap_release_streak
            nonlocal fist_engage_streak, fist_release_streak
            if cursor.is_holding:
                cursor.click_up()
                logger.info("Gesture click: released (hand lost / mouse override)")
            hull_on = pinch_on = fist_on = False
            hull_engage_streak = hull_release_streak = 0
            click_gap_engage_streak = click_gap_release_streak = 0
            fist_engage_streak = fist_release_streak = 0
            click_held_through = False  # hand-lost / override clears the repeat lock

        def _reset_tracking(*, hard: bool) -> None:
            """The one place every "abandon the current cursor drive" path
            resets shared state, so a path can't silently forget a field.
            `hard` (hand lost past the coast window) also steps the warmup
            streak back; `hard=False` is the physical-mouse yield.
            """
            nonlocal prev_filtered, prev_primary, click_freeze, preclick_freeze
            nonlocal hull_prev, pinch_prev, fist_prev, seen
            nonlocal scroll_on, scroll_enter_streak, scroll_exit_streak
            nonlocal scroll_anchor_y, scroll_accum, mid_buf, open_palm_streak
            _release_click()
            euro.reset()
            prev_filtered = None
            prev_primary = None
            click_freeze = 0
            preclick_freeze = 0
            hull_prev = pinch_prev = fist_prev = None
            scroll_on = False
            scroll_enter_streak = scroll_exit_streak = 0
            scroll_anchor_y = None
            scroll_accum = 0.0
            mid_buf = []
            open_palm_streak = 0
            if hard:
                seen = max(0, seen - 1)

        max_step_px = min(MAX_CURSOR_STEP_FRAC * min(screen_w, screen_h), float(MAX_CURSOR_STEP_PX))

        def _drive_cursor(tx: float, ty: float) -> tuple[float, float]:
            """Move the cursor toward an absolute screen point: clamp the
            per-tick step so a bad frame can't fling it across the display,
            re-anchor the physical-mouse reference every tick (even when we
            don't move). Returns the FLOAT target after clamping — the caller
            keeps that as its accumulator so sub-pixel motion still adds up."""
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
            dz = float(deadzone_px)  # personal on-screen deadzone (STEADY calibration)
            step = math.hypot(dx, dy)
            if GESTURE_DIAG:
                diag_step_out.append(step)
            if abs(dx) >= dz or abs(dy) >= dz:
                cursor.move_cursor(int(round(tx)), int(round(ty)))
                if GESTURE_DIAG:
                    diag_n_moved += 1
                    diag_travel += step
                actual = cursor.last_pos()
                if actual is not None and (
                    abs(actual[0] - tx) > 4 or abs(actual[1] - ty) > 4
                ):
                    # OS clamped the pointer short of the target (dock/panel)
                    # — keep the accumulator on the reachable point so it
                    # can't wind up and jam control against that edge.
                    return float(actual[0]), float(actual[1])
                return tx, ty
            cursor.sync_last_set()
            return tx, ty

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
                    logger.info(
                        "Gesture cursor: at (%d,%d) on %dx%d | edge-dist L=%d R=%d T=%d B=%d | "
                        "travelled %d px over %.1fs | step %s | clamp hit %d/%d (cap %d px)",
                        cxp, cyp, screen_w, screen_h,
                        cxp, screen_w - cxp, cyp, screen_h - cyp,
                        int(diag_travel), elapsed, _rng(diag_step_out, ".0f"),
                        diag_clamped, diag_ticks, int(max_step_px),
                    )
                    logger.info(
                        "Gesture hand: tip x %s y %s | zone x[%.2f-%.2f] y[%.2f-%.2f] | "
                        "ticks: moved %d%% clutch %d%% scroll %d%% openpalm %d%% "
                        "preclick %d%% clickfreeze %d%% | phys-yield %d | bones %s",
                        _rng(diag_hx), _rng(diag_hy),
                        bounds[0], bounds[1], bounds[2], bounds[3],
                        100 * diag_n_moved // n, 100 * diag_n_clutch // n,
                        100 * diag_n_arm // n, 100 * diag_n_open // n,
                        100 * diag_n_preclick // n, 100 * diag_n_clickfreeze // n,
                        diag_phys, "ready" if bones.ready else "scanning",
                    )
                    logger.info(
                        "Gesture click-signals: fist* %s (L-click eng<=%.2f rel>=%.2f, "
                        "👍 fb<=%.2f) | gap %s | hull %s (%s) | straight idx %s mid %s "
                        "(pt>%.2f) ring %s pinky %s",
                        _rng(diag_fist), click_gap_eng, click_gap_rel, FIST_FALLBACK_RATIO,
                        _rng(diag_pinch2),
                        _rng(diag_hull), "on" if CLICK_USE_HULL else "off",
                        _rng(diag_idx), _rng(diag_mid), MOVE_FINGER_RATIO,
                        _rng(diag_ring), _rng(diag_pnk),
                    )
                    diag_since = loop_start
                    diag_ticks = 0
                    diag_fist = []
                    diag_pinch2 = []
                    diag_hull = []
                    diag_idx = []
                    diag_mid = []
                    diag_ring = []
                    diag_pnk = []
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
                    diag_n_arm = 0
                    diag_n_open = 0
                    diag_n_preclick = 0
                    diag_n_clickfreeze = 0
                    diag_n_moved = 0
                    diag_travel = 0.0
                if self._recalibrate:  # button pressed while already active
                    self._recalibrate = False
                    session = calibration.CalibrationSession(px_per_norm=px_per_norm)
                    self._drain_calibration_prompt(session)
                    overlay_state.set_calibration(session.progress())
                if self._cancel_calibration:
                    self._cancel_calibration = False
                    if session is not None:
                        session = None
                        overlay_state.set_calibration(None)
                        self._announce("Калибровка отменена.")

                try:
                    result = tracker.read()
                except CameraUnavailable as exc:
                    logger.warning("Gesture worker stopping: %s", exc)
                    self._last_error = str(exc)
                    self._announce(f"Режим жестов остановлен: {exc}.")
                    break
                if result is None:
                    self._stop_event.wait(frame_interval)
                    continue

                if not activated:
                    activated = True
                    overlay_state.set(active=True)
                    cursor_zoom.enlarge()

                if self._preview_enabled:
                    with self._preview_lock:
                        self._preview_source = (result.frame, [list(h) for h in result.hands])

                # Physical mouse always wins.
                if cursor.physical_mouse_moved(PHYSICAL_MOUSE_THRESHOLD_PX):
                    override_until = loop_start + PHYSICAL_MOUSE_OVERRIDE_SECONDS
                    diag_phys += 1
                    _release_click()
                if loop_start < override_until:
                    _reset_tracking(hard=False)
                    cursor.sync_last_set()
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
                    # A held click gets a much longer coast — a pinch hides
                    # the hand from MediaPipe far more than an open hand, and
                    # ~half of pinch-clicks were dying mid-press otherwise.
                    coast_limit = (
                        FIST_LOST_GRACE_FRAMES if cursor.is_holding else HAND_LOST_COAST_FRAMES
                    )
                    if hand_lost <= coast_limit:
                        self._pace(loop_start, frame_interval)
                        continue
                    _reset_tracking(hard=True)
                    self._pace(loop_start, frame_interval)
                    continue
                hand_lost = 0

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
                # stretch its segment. Skip scan frames that are an active
                # grip (a curled finger would bias the learned lengths). ---
                pre_str = finger_straightness(primary)
                if BONE_FIT_ENABLED:
                    if not bones.ready:
                        if session is None:
                            # Skip only a full fist (every finger curled) — a
                            # closed hand would bias the learned bone lengths.
                            is_grip = max(pre_str) <= FIST_FALLBACK_RATIO
                            bones.observe(primary, skip=is_grip)
                        if bones.ready and not bone_ready_logged:
                            bone_ready_logged = True
                            logger.info(
                                "Gesture bone model: ready (%d clean frames)", bones.scanned
                            )
                    else:
                        primary = bones.fit(primary)

                prev_primary = hand_centre(primary)
                tracked_pt = index_tip(primary)
                idx_s, mid_s, ring_s, pinky_s = finger_straightness(primary)
                thumb_g = thumb_gap(primary)
                # MOVE = the index finger is extended and we're not in the
                # SCROLL pose. The middle finger being up no longer *freezes*
                # the cursor (its straightness is too noisy for that), but
                # both-fingers-clearly-up + debounce IS the scroll pose.
                index_up = idx_s > MOVE_FINGER_RATIO
                middle_up = mid_s > MOVE_FINGER_RATIO
                # OPEN PALM = fingers up (index extended) AND the thumb spread
                # away — a deliberate "do nothing" pose so the hand can be
                # repositioned between gestures. 2-frame dwell so a stray thumb
                # blip while pointing can't freeze the cursor.
                open_palm_streak = (
                    open_palm_streak + 1
                    if (index_up and thumb_g >= THUMB_GAP_MIN)
                    else 0
                )
                open_palm = open_palm_streak >= 2
                # median-smooth the noisy middle-finger signal for the scroll
                # pose test so it can't flip modes frame to frame.
                mid_buf.append(mid_s)
                if len(mid_buf) > SCROLL_MID_WINDOW:
                    mid_buf.pop(0)
                mid_med = sorted(mid_buf)[len(mid_buf) // 2]
                both_up = index_up and mid_med > SCROLL_MIDDLE_MIN and not open_palm
                still_two = index_up and mid_med > SCROLL_MIDDLE_STAY and not open_palm
                if not scroll_on:
                    scroll_enter_streak = scroll_enter_streak + 1 if both_up else 0
                    if scroll_enter_streak >= SCROLL_ENTER_FRAMES:
                        scroll_on, scroll_enter_streak = True, 0
                        scroll_anchor_y = None  # (re)seeded on the first scroll frame
                        scroll_accum = 0.0
                else:
                    scroll_exit_streak = scroll_exit_streak + 1 if not still_two else 0
                    if scroll_exit_streak >= SCROLL_EXIT_FRAMES:
                        scroll_on, scroll_exit_streak = False, 0
                        scroll_anchor_y = None
                # `scrolling_now` (instant) frees the cursor the moment the
                # middle finger drops — `scroll_on` (debounced) only keeps the
                # accum alive across a 1-frame blip.
                scrolling_now = scroll_on and still_two
                move_pose = index_up and not scrolling_now and not open_palm
                click_arm = index_up and middle_up  # diag only now
                pointing = index_up
                # fist_s = MEDIAN straightness of the four fingers (mean of the
                # middle two). Median, not max, so one stray half-extended
                # finger can't break an otherwise-closed fist -> the 👍 right
                # click stops firing "через раз".
                _s_sorted = sorted((idx_s, mid_s, ring_s, pinky_s))
                fist_s = min(
                    FIST_SCORE_MAX,
                    max(FIST_SCORE_MIN, 0.5 * (_s_sorted[1] + _s_sorted[2])),
                )
                gap_s = min(CLICK_GAP_MAX, index_middle_gap(primary))
                hull_s = min(HULL_SCORE_MAX, hull_compactness(primary))
                if GESTURE_DIAG:
                    diag_fist.append(fist_s)
                    diag_pinch2.append(gap_s)
                    diag_hull.append(hull_s)
                    diag_idx.append(idx_s)
                    diag_mid.append(mid_s)
                    diag_ring.append(ring_s)
                    diag_pnk.append(pinky_s)

                # --- calibration wizard ---
                if session is not None and not session.done:
                    session.observe(
                        calibration.CalibrationFrame(
                            tip=tracked_pt,
                            index_middle_gap=gap_s,
                            pointing=pointing,
                            brightness=result.brightness,
                            fist=fist_s,
                        )
                    )
                    self._drain_calibration_prompt(session)
                    overlay_state.set_calibration(session.progress())
                    if session.done:
                        applied = session.persist()
                        if not session.aborted:
                            click_gap_eng = applied.click_gap_engage
                            click_gap_rel = applied.click_gap_release
                            deadzone_px = applied.deadzone_px
                            euro.set_min_cutoff(applied.min_cutoff)
                            if applied.zone_bounds is not None:
                                bounds = applied.zone_bounds
                                px_per_norm = screen_w / max(bounds[1] - bounds[0], 1e-6)
                            logger.info(
                                "Gesture: calibration applied — zone %s click-gap %.2f/%.2f "
                                "deadzone %dpx cutoff %.2f",
                                tuple(round(b, 2) for b in bounds),
                                click_gap_eng, click_gap_rel, deadzone_px, applied.min_cutoff,
                            )
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

                # --- medians: the click decisions need a stable signal ---
                fist_buf.append(fist_s)
                if len(fist_buf) > CLICK_MEDIAN_WINDOW:
                    fist_buf.pop(0)
                fist_med = sorted(fist_buf)[len(fist_buf) // 2]
                pinch_buf.append(gap_s)
                if len(pinch_buf) > CLICK_MEDIAN_WINDOW:
                    pinch_buf.pop(0)
                pinch_med = sorted(pinch_buf)[len(pinch_buf) // 2]
                hull_buf.append(hull_s)
                if len(hull_buf) > CLICK_MEDIAN_WINDOW:
                    hull_buf.pop(0)
                hull_med = sorted(hull_buf)[len(hull_buf) // 2]

                # --- pre-click freeze: the fist signal dropping fast AND
                # already past halfway to closed freezes the cursor for a few
                # ticks, so the closing arc into a fist can't drag the pointer
                # off target. Gated on `fist_med < click_gap_rel` so the
                # signal's frame-to-frame noise while just aiming (fist_med
                # high) can't trip it — that was freezing the cursor mid-aim,
                # especially with the hand turned side-on. ---
                closing = (
                    fist_prev is not None
                    and fist_prev - fist_med > PRECLICK_DELTA
                    and fist_med < click_gap_rel
                )
                hull_prev, pinch_prev, fist_prev = hull_med, pinch_med, fist_med
                if closing:
                    preclick_freeze = PRECLICK_FREEZE_FRAMES

                # --- filtered fingertip ---
                filtered = euro.update(tracked_pt, result.capture_t)
                now_t = result.capture_t
                if prev_filtered is not None and now_t > prev_t:
                    d_hand = (filtered[0] - prev_filtered[0], filtered[1] - prev_filtered[1])
                else:
                    d_hand = (0.0, 0.0)
                prev_filtered, prev_t = filtered, now_t

                # --- scroll: in the two-finger pose the cursor is already
                # held (move_pose is False); vertical fingertip travel past a
                # deadzone turns the wheel, rate-limited per tick. ---
                if scrolling_now:
                    if scroll_anchor_y is None:
                        scroll_anchor_y = filtered[1]
                    dy = filtered[1] - scroll_anchor_y  # +down (y grows down), -up
                    if abs(dy) > SCROLL_DEADZONE_NORM:
                        scroll_accum += dy
                        scroll_anchor_y = filtered[1]
                    clicks = int(scroll_accum / SCROLL_STEP_NORM)
                    if clicks:
                        clicks = max(
                            -SCROLL_MAX_CLICKS_PER_TICK,
                            min(SCROLL_MAX_CLICKS_PER_TICK, clicks),
                        )
                        scroll_accum -= clicks * SCROLL_STEP_NORM
                        # finger up (dy<0 -> clicks<0) -> wheel up (positive)
                        cursor.scroll(clicks if SCROLL_INVERT else -clicks)
                else:
                    scroll_anchor_y = None  # re-seed on the next scroll run

                if click_freeze > 0:
                    click_freeze -= 1
                if preclick_freeze > 0:
                    preclick_freeze -= 1

                if GESTURE_DIAG:
                    diag_ticks += 1
                    diag_hx.append(filtered[0])
                    diag_hy.append(filtered[1])
                    if open_palm:
                        diag_n_open += 1
                    elif not move_pose and not cursor.is_holding and not scrolling_now:
                        diag_n_clutch += 1
                    if scrolling_now:
                        diag_n_arm += 1
                    if preclick_freeze > 0:
                        diag_n_preclick += 1
                    if click_freeze > 0:
                        diag_n_clickfreeze += 1

                # ABSOLUTE mapping. The cursor is driven ONLY in the MOVE pose
                # (index up, middle curled) — raising the middle finger to arm
                # a click freezes it in place, and any other pose is the
                # clutch. A drag is the exception: once the button is held the
                # cursor follows again even though the middle finger is up.
                # Also holds during a click / pre-click freeze so the press
                # lands where it was aimed.
                can_move = move_pose or cursor.is_holding
                hold_cursor = (
                    not can_move
                    or click_freeze > 0
                    or (preclick_freeze > 0 and not cursor.is_holding)
                )
                if hold_cursor:
                    cursor.sync_last_set()
                    cursor_px, cursor_py = (float(v) for v in cursor.current_pos())
                else:
                    tx, ty = map_hand_to_screen(filtered, (screen_w, screen_h), bounds)
                    # Ease toward the mapped point instead of snapping there
                    # (EMA): pointing somewhere far glides over ~0.3 s, so
                    # there's time to react. ABS_FOLLOW_RATE is the one knob.
                    cx, cy = cursor.current_pos()
                    cursor_px = cx + ABS_FOLLOW_RATE * (tx - cx)
                    cursor_py = cy + ABS_FOLLOW_RATE * (ty - cy)
                    cursor_px, cursor_py = _drive_cursor(cursor_px, cursor_py)

                # --- click: PINCH (thumb-index) + DEEP FIST, catch-fast /
                # release-slow, OR'd onto the one OS button, with a tap
                # timeout and a hard max-hold. HULL is off by default — its
                # frame-to-frame noise fired false clicks. ---
                if CLICK_USE_HULL:
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

                # LEFT click = curl ALL FOUR fingers into a fist, thumb NOT
                # out (thumb out = the 👍 right click). `fist_med` = median
                # finger straightness: catch below `click_gap_eng`, release
                # above `click_gap_rel` (both personalised by the CLICK
                # calibration phase, unit = straightness). Robust where the
                # old "tips together" gap wasn't — MediaPipe keeps a closing
                # fist in view.
                thumb_tucked = thumb_g < THUMB_TUCKED_MAX  # clearly wrapped in -> fist
                pinch_on = False  # the index<->middle gap click is retired
                # A fist = median straightness low AND both reliable fingers
                # (index, middle) clearly curled AND the thumb clearly tucked.
                # It RELEASES the moment the thumb stops being tucked, so the
                # click ends cleanly before the next gesture (and the 0.28..
                # 0.36 thumb band fires neither click).
                fist_closed = (
                    fist_med <= click_gap_eng
                    and idx_s < MIDDLE_DOWN_MAX
                    and mid_s < MIDDLE_DOWN_MAX
                    and thumb_tucked
                )
                fist_open = (
                    fist_med >= click_gap_rel
                    or not thumb_tucked
                    or idx_s > MOVE_FINGER_RATIO
                )
                if not fist_on:
                    fist_engage_streak = fist_engage_streak + 1 if fist_closed else 0
                    if fist_engage_streak >= CLICK_ENGAGE_FRAMES:
                        fist_on, fist_engage_streak = True, 0
                else:
                    fist_release_streak = fist_release_streak + 1 if fist_open else 0
                    if fist_release_streak >= CLICK_RELEASE_FRAMES:
                        fist_on, fist_release_streak = False, 0

                want_click = fist_on or (CLICK_USE_HULL and hull_on)
                held = cursor.is_holding
                still_squeezed = fist_closed or (CLICK_USE_HULL and hull_med <= HULL_ENGAGE)
                # "Clearly open" = the signal well past its release bar, not
                # just above the engage bar. The repeat lock (armed on every
                # click-up) lifts only after the hand has held this for
                # CLICK_RELEASE_FRAMES — a genuine release re-clicks at once
                # (double-click) but a hand oscillating around the engage
                # threshold, which never gets here, can't machine-gun.
                hand_open_now = fist_open and (
                    not CLICK_USE_HULL or hull_med >= HULL_RELEASE
                )
                open_streak = open_streak + 1 if hand_open_now else 0
                if open_streak >= CLICK_RELEASE_FRAMES:
                    click_held_through = False
                repeat_locked = click_held_through and loop_start < click_lock_until
                held_for = loop_start - click_down_t
                # A click is a tap by default: once it's been down a moment
                # and no signal is still actively squeezed, end it — don't
                # wait for the absolute release bars, which sit in this
                # user's relaxed-hand noise.
                tap_done = held and held_for > CLICK_TAP_SECONDS and not still_squeezed
                sig = "fist" if fist_on else "hull"
                if want_click and not held and not repeat_locked:
                    cursor.click_down()
                    click_down_t = loop_start
                    click_freeze = CLICK_FREEZE_FRAMES
                    logger.info(
                        "Gesture click: down via %s (hull=%.3f pinch=%.3f fist=%.2f)",
                        sig, hull_med, pinch_med, fist_med,
                    )
                elif held and (not want_click or tap_done):
                    cursor.click_up()
                    # Arm the repeat lock unconditionally; it lifts as soon as
                    # the hand is clearly open (open_streak above) or after
                    # CLICK_REPEAT_LOCKOUT_S. Zero the engage streaks too so a
                    # lingering sub-threshold signal can't instantly re-arm.
                    click_held_through = True
                    click_lock_until = loop_start + CLICK_REPEAT_LOCKOUT_S
                    hull_on = pinch_on = fist_on = False
                    hull_release_streak = click_gap_release_streak = fist_release_streak = 0
                    hull_engage_streak = click_gap_engage_streak = fist_engage_streak = 0
                    # Opening a fist pops the thumb out while the fingers are
                    # still curled — that read as a thumbs-up and fired a stray
                    # right click right after almost every left click. Briefly
                    # lock the right click out (short — the hand opens fast).
                    right_streak = 0
                    right_lock_until = loop_start + RIGHT_AFTER_LEFT_LOCKOUT_S
                    logger.info(
                        "Gesture click: up after %.2fs%s (hull=%.3f pinch=%.3f fist=%.2f)",
                        held_for, " [tap]" if tap_done and want_click else "",
                        hull_med, pinch_med, fist_med,
                    )
                elif held and held_for > CLICK_MAX_HOLD_SECONDS:
                    cursor.click_up()
                    click_held_through = True
                    click_lock_until = loop_start + CLICK_REPEAT_LOCKOUT_S
                    hull_on = pinch_on = fist_on = False
                    hull_release_streak = click_gap_release_streak = fist_release_streak = 0
                    hull_engage_streak = click_gap_engage_streak = fist_engage_streak = 0
                    right_streak = 0
                    right_lock_until = loop_start + RIGHT_AFTER_LEFT_LOCKOUT_S
                    logger.warning(
                        "Gesture click: force-released after %.1fs (hull=%.3f pinch=%.3f fist=%.2f)",
                        held_for, hull_med, pinch_med, fist_med,
                    )

                # --- right click: a THUMBS-UP (fingers curled + thumb out).
                # Fire-once, then locked until the pose ends or the lockout.
                thumbs_up = fist_med <= FIST_FALLBACK_RATIO and thumb_g >= THUMB_GAP_MIN
                if not thumbs_up:
                    right_streak = 0
                    if loop_start >= right_lock_until:
                        right_lock_until = 0.0
                elif right_lock_until == 0.0:
                    right_streak += 1
                    if right_streak >= RIGHT_CLICK_FRAMES and not cursor.is_holding:
                        cursor.right_click()
                        right_streak = 0
                        right_lock_until = loop_start + RIGHT_CLICK_LOCKOUT_S
                        # don't let the thumb tucking back in after 👍 instantly
                        # re-arm a left-click fist (but no long lockout — that
                        # made the next real fist feel dead).
                        fist_engage_streak = 0
                        logger.info(
                            "Gesture click: RIGHT (thumbs-up, fist=%.2f thumb=%.2f)",
                            fist_med, thumb_g,
                        )

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
            # Last: mark the worker finished so is_active() flips even before
            # the OS thread has fully unwound, and stop() can reap the handle.
            self._worker_done.set()

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


async def _handle_gesture_calibrate_cancel(_params: dict[str, Any]) -> dict[str, Any]:
    if not gesture_controller.cancel_calibration():
        return {"message": "Калибровка не запущена."}
    return {"message": "Отменяю калибровку."}


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
    dispatcher.register(
        "gesture_calibrate_cancel",
        _handle_gesture_calibrate_cancel,
        dangerous=False,
        description="Прервать идущий мастер калибровки жестов (ничего не сохраняется).",
    )
