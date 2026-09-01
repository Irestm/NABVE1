from __future__ import annotations

import collections
import time

import pytest

import modules.gesture_control.dispatcher as gd
from core.message_bus import MessageBus
from modules.gesture_control.hand_tracker import FrameResult

# --- synthetic 21-point hands ---------------------------------------------
# Offsets from the palm centre (cx, cy): wrist +0.15 below, middle knuckle
# -0.15 above => hand_scale 0.30. Curled fingers have BENT joints so the
# straightness metric (chord/path) reads them as curled (~0.3), extended
# ones read ~0.97.
#   "point"    = ONLY the index straight (middle/ring/pinky curled) -> MOVE.
#   "arm"      = index + middle straight and apart -> cursor held, no click.
#   "click"    = all four fingers curled, thumb tucked -> LEFT click (a fist).
#   "onlymid"  = middle straight, index curled -> nothing (cursor held).
#   "fist"     = same as "click" (all curled, thumb tucked) -> LEFT click.
#   "thumbsup" = all curled + thumb tip far from fingers -> right click.
_STRAIGHT_INDEX = {5: (-0.05, -0.13), 6: (-0.06, -0.22), 7: (-0.07, -0.28), 8: (-0.10, -0.34)}
_STRAIGHT_MIDDLE = {9: (0.00, -0.15), 10: (0.01, -0.24), 11: (0.02, -0.30), 12: (0.04, -0.36)}
_CURL_INDEX = {5: (-0.05, -0.13), 6: (-0.05, -0.20), 7: (-0.05, -0.14), 8: (-0.05, -0.08)}
_CURL_MIDDLE = {9: (0.00, -0.15), 10: (0.00, -0.22), 11: (0.00, -0.15), 12: (0.00, -0.09)}
_CURL_RING = {13: (0.05, -0.13), 14: (0.05, -0.20), 15: (0.05, -0.14), 16: (0.05, -0.08)}
_CURL_PINKY = {17: (0.09, -0.12), 18: (0.09, -0.18), 19: (0.09, -0.13), 20: (0.09, -0.08)}
_THUMB_TUCKED = {1: (-0.09, 0.06), 2: (-0.08, 0.03), 3: (-0.03, -0.01), 4: (0.02, -0.03)}
_THUMB_OUT = {1: (-0.10, 0.06), 2: (-0.13, 0.00), 3: (-0.17, -0.06), 4: (-0.21, -0.12)}


def _hand(cx: float, cy: float, pose: str = "point") -> list[tuple[float, float]]:
    parts: dict[int, tuple[float, float]] = {0: (0.00, 0.15)}
    parts.update(_CURL_RING)
    parts.update(_CURL_PINKY)
    parts.update(_THUMB_TUCKED)
    if pose in ("fist", "thumbsup", "click"):
        parts.update(_CURL_INDEX)
        parts.update(_CURL_MIDDLE)
        if pose == "thumbsup":
            parts.update(_THUMB_OUT)
    elif pose == "onlymid":
        parts.update(_CURL_INDEX)
        parts.update(_STRAIGHT_MIDDLE)
    elif pose == "point":
        parts.update(_STRAIGHT_INDEX)
        parts.update(_CURL_MIDDLE)
    elif pose == "open":  # index+middle straight AND thumb spread -> do nothing
        parts.update(_STRAIGHT_INDEX)
        parts.update(_STRAIGHT_MIDDLE)
        parts.update(_THUMB_OUT)
    else:  # "arm" — index + middle both straight, apart, thumb tucked
        parts.update(_STRAIGHT_INDEX)
        parts.update(_STRAIGHT_MIDDLE)
    return [(cx + dx, cy + dy) for _i, (dx, dy) in sorted(parts.items())]


# --- fakes --------------------------------------------------------------


class _ScriptedTracker:
    def __init__(self, *_a, **_k) -> None:
        self._q: collections.deque[list[list[tuple[float, float]]]] = collections.deque()
        self._raise: BaseException | None = None
        self.consumed = 0
        self.closed = False
        self._t = 1000.0

    def feed(self, hands: list[list[tuple[float, float]]]) -> None:
        self._q.append([list(h) for h in hands])

    def raise_after(self, exc: BaseException) -> None:
        self._raise = exc

    def open(self) -> None:
        pass

    def read(self):
        if not self._q:
            if self._raise is not None:
                exc, self._raise = self._raise, None
                raise exc
            return None
        hands = self._q.popleft()
        self.consumed += 1
        self._t += 0.02
        return FrameResult(frame=None, hands=hands, brightness=120.0, capture_t=self._t)

    def close(self) -> None:
        self.closed = True


class _RecordingCursor:
    def __init__(self) -> None:
        self.screen_size = (1920, 1080)
        self._pos = [960.0, 540.0]
        self._last_set: tuple[int, int] | None = None
        self.moves: list[tuple[int, int]] = []
        self.downs = 0
        self.ups = 0
        self.rights = 0
        self.scrolls: list[int] = []
        self._button = False
        self._phantom = 0

    def current_pos(self) -> tuple[int, int]:
        return int(self._pos[0]), int(self._pos[1])

    def move_cursor(self, x: int, y: int) -> None:
        self._pos = [float(x), float(y)]
        self._last_set = (x, y)
        self.moves.append((x, y))

    def last_pos(self) -> tuple[int, int] | None:
        return self._last_set

    def sync_last_set(self) -> None:
        self._last_set = self.current_pos()

    def scroll(self, clicks: int) -> None:
        if clicks:
            self.scrolls.append(int(clicks))

    def arm_physical_move(self, frames: int = 1) -> None:
        self._phantom = frames

    def physical_mouse_moved(self, _threshold_px: int) -> bool:
        if self._phantom > 0:
            self._phantom -= 1
            return True
        return False

    def click_down(self) -> None:
        if not self._button:
            self._button = True
            self.downs += 1

    def click_up(self) -> None:
        if self._button:
            self._button = False
            self.ups += 1

    def right_click(self) -> None:
        self.click_up()
        self.rights += 1

    @property
    def is_holding(self) -> bool:
        return self._button

    def release(self) -> None:
        self.click_up()


@pytest.fixture(autouse=True)
def _stub_env(monkeypatch):
    monkeypatch.setattr(gd.calibration, "load_min_cutoff", lambda: 1.0)
    monkeypatch.setattr(gd.calibration, "load_deadzone_px", lambda: 2)
    monkeypatch.setattr(gd.calibration, "load_click_gap_thresholds", lambda: (0.55, 0.75))
    monkeypatch.setattr(gd.calibration, "load_zone_bounds", lambda: None)
    monkeypatch.setattr(gd.cursor_zoom, "enlarge", lambda: None)
    monkeypatch.setattr(gd.cursor_zoom, "restore", lambda: None)


def _make(monkeypatch, *, fps: int = 500):
    monkeypatch.setattr(gd, "PROCESSING_FPS", fps)
    tracker = _ScriptedTracker()
    cursor = _RecordingCursor()
    monkeypatch.setattr(gd, "HandTracker", lambda *a, **k: tracker)
    monkeypatch.setattr(gd, "CursorController", lambda *a, **k: cursor)
    controller = gd.GestureController(bus=MessageBus())
    return tracker, cursor, controller


def _pump(tracker: _ScriptedTracker, n: int, timeout: float = 4.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if tracker.consumed >= n:
            return
        time.sleep(0.01)
    raise AssertionError(f"worker consumed {tracker.consumed}/{n} frames")


def _wait_stopped(controller: gd.GestureController, timeout: float = 4.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not controller.is_active():
            return
        time.sleep(0.01)
    raise AssertionError("worker never stopped")


def _wait_for(pred, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met in time")


# --- cursor: absolute mapping ------------------------------------------


def test_pointing_hand_drives_the_cursor_to_the_mapped_point(monkeypatch) -> None:
    tracker, cursor, controller = _make(monkeypatch)
    for _ in range(25):
        tracker.feed([_hand(0.5, 0.6, "point")])
    controller.start()
    try:
        _pump(tracker, 25)
    finally:
        controller.stop()
    assert cursor.moves, "pointing hand never moved the cursor"
    # default zone (0.2..0.8); tip ~ (0.43, 0.28) -> x ~ 0.38 of the screen
    x, _y = cursor.moves[-1]
    assert 500 < x < 950


def test_cursor_follows_the_pointing_hand_across_the_frame(monkeypatch) -> None:
    tracker, cursor, controller = _make(monkeypatch)
    for i in range(45):
        tracker.feed([_hand(0.35 + min(i, 20) * 0.012, 0.55, "point")])
    controller.start()
    try:
        _pump(tracker, 45)
    finally:
        controller.stop()
    assert cursor.moves[-1][0] > cursor.moves[0][0] + 100


def test_non_pointing_pose_holds_the_cursor(monkeypatch) -> None:
    tracker, cursor, controller = _make(monkeypatch)
    for _ in range(10):
        tracker.feed([_hand(0.5, 0.55, "point")])   # establish a position
    for _ in range(20):
        tracker.feed([_hand(0.5, 0.55, "fist")])    # fist = not pointing -> hold
    controller.start()
    try:
        _pump(tracker, 30)
    finally:
        controller.stop()
    settled = cursor.moves[9][0] if len(cursor.moves) > 9 else cursor.moves[-1][0]
    assert all(abs(m[0] - settled) < 40 for m in cursor.moves[10:])


def test_middle_finger_alone_does_nothing(monkeypatch) -> None:
    tracker, cursor, controller = _make(monkeypatch, fps=200)
    for _ in range(10):
        tracker.feed([_hand(0.5, 0.55, "point")])
    for _ in range(20):
        tracker.feed([_hand(0.3, 0.3, "onlymid")])
    controller.start()
    try:
        _pump(tracker, 30)
    finally:
        controller.stop()
    settled = cursor.moves[9][0] if len(cursor.moves) > 9 else cursor.moves[-1][0]
    assert all(abs(m[0] - settled) < 40 for m in cursor.moves[10:])
    assert cursor.downs == 0 and cursor.rights == 0


def test_no_hand_leaves_the_cursor_alone(monkeypatch) -> None:
    tracker, cursor, controller = _make(monkeypatch)
    for _ in range(20):
        tracker.feed([])
    controller.start()
    try:
        _pump(tracker, 20)
    finally:
        controller.stop()
    assert cursor.moves == []


# --- scroll: two fingers up -----------------------------------------


def test_two_fingers_up_scrolls_on_vertical_travel(monkeypatch) -> None:
    tracker, cursor, controller = _make(monkeypatch, fps=200)
    for _ in range(10):
        tracker.feed([_hand(0.5, 0.60, "arm")])            # settle into scroll pose
    for i in range(40):
        tracker.feed([_hand(0.5, 0.60 - i * 0.01, "arm")])  # fingertip travels UP
    controller.start()
    try:
        _pump(tracker, 50)
    finally:
        controller.stop()
    assert cursor.scrolls, "two-finger vertical travel produced no wheel events"
    assert sum(cursor.scrolls) > 0                         # finger up -> wheel up
    assert cursor.downs == 0                               # not a click
    # the cursor is held while scrolling
    assert not cursor.moves or all(m == cursor.moves[0] for m in cursor.moves)


def test_open_palm_does_nothing(monkeypatch) -> None:
    # A fully open palm (index up + thumb spread) is the "reposition" pose:
    # cursor held, no scroll, no click, whatever the hand does.
    tracker, cursor, controller = _make(monkeypatch, fps=200)
    for _ in range(16):
        tracker.feed([_hand(0.5, 0.55, "point")])           # settle onto a position
    controller.start()
    try:
        _pump(tracker, 16)
        _wait_for(lambda: len(cursor.moves) >= 1)
        time.sleep(0.05)
        settled = len(cursor.moves)
        for i in range(30):
            tracker.feed([_hand(0.30 + i * 0.013, 0.30, "open")])  # open + travel
        _pump(tracker, 46)
        time.sleep(0.05)
    finally:
        controller.stop()
    # a few transition frames may still land while the median/dwell catches
    # up, but the cursor must not chase the open hand across the zone
    assert len(cursor.moves) - settled <= 8
    assert cursor.downs == 0 and cursor.rights == 0 and cursor.scrolls == []


def test_two_fingers_still_do_not_scroll(monkeypatch) -> None:
    tracker, cursor, controller = _make(monkeypatch, fps=200)
    for _ in range(40):
        tracker.feed([_hand(0.5, 0.55, "arm")])            # both up but not moving
    controller.start()
    try:
        _pump(tracker, 40)
    finally:
        controller.stop()
    assert cursor.scrolls == []


# --- click: finger state ----------------------------------------------


def test_fist_is_a_left_click(monkeypatch) -> None:
    # LEFT click = curl all four fingers into a fist (thumb tucked).
    tracker, cursor, controller = _make(monkeypatch, fps=200)
    for _ in range(6):
        tracker.feed([_hand(0.5, 0.55, "point")])
    for _ in range(8):
        tracker.feed([_hand(0.5, 0.55, "fist")])
    for _ in range(8):
        tracker.feed([_hand(0.5, 0.55, "point")])
    controller.start()
    try:
        _pump(tracker, 22)
    finally:
        controller.stop()
    assert cursor.downs >= 1 and cursor.ups >= 1
    assert cursor.rights == 0  # a plain fist must NOT right-click


def test_opening_a_fist_does_not_stray_right_click(monkeypatch) -> None:
    # Opening a fist pops the thumb out while the fingers are still curled;
    # that briefly looks like a thumbs-up. The post-left-click lockout must
    # swallow it.
    tracker, cursor, controller = _make(monkeypatch, fps=200)
    for _ in range(6):
        tracker.feed([_hand(0.5, 0.55, "point")])
    for _ in range(8):
        tracker.feed([_hand(0.5, 0.55, "fist")])       # left click
    for _ in range(8):
        tracker.feed([_hand(0.5, 0.55, "thumbsup")])   # fist-open blip -> would-be right
    controller.start()
    try:
        _pump(tracker, 22)
    finally:
        controller.stop()
    assert cursor.downs >= 1        # the left click happened
    assert cursor.rights == 0       # ...and no stray right click followed


def test_thumbs_up_is_a_right_click(monkeypatch) -> None:
    tracker, cursor, controller = _make(monkeypatch, fps=200)
    for _ in range(6):
        tracker.feed([_hand(0.5, 0.55, "point")])
    for _ in range(10):
        tracker.feed([_hand(0.5, 0.55, "thumbsup")])
    controller.start()
    try:
        _pump(tracker, 16)
    finally:
        controller.stop()
    assert cursor.rights >= 1
    assert cursor.downs == 0  # a thumbs-up must NOT also left-click


def test_held_click_does_not_machine_gun(monkeypatch) -> None:
    monkeypatch.setattr(gd, "CLICK_TAP_SECONDS", 0.05)
    monkeypatch.setattr(gd, "CLICK_REPEAT_LOCKOUT_S", 0.2)
    tracker, cursor, controller = _make(monkeypatch, fps=200)
    for _ in range(100):
        tracker.feed([_hand(0.5, 0.55, "click")])
    controller.start()
    try:
        _pump(tracker, 100)
    finally:
        controller.stop()
    assert cursor.downs <= 4


def test_drag_moves_the_held_cursor(monkeypatch) -> None:
    tracker, cursor, controller = _make(monkeypatch, fps=200)
    for _ in range(6):
        tracker.feed([_hand(0.40, 0.55, "point")])
    for _ in range(5):
        tracker.feed([_hand(0.40, 0.55, "click")])
    for i in range(30):
        tracker.feed([_hand(0.40 + min(i, 14) * 0.02, 0.55, "click")])
    controller.start()
    try:
        _pump(tracker, 41)
    finally:
        controller.stop()
    assert cursor.downs >= 1
    assert cursor.moves[-1][0] > cursor.moves[0][0] + 60


# --- robustness (kept from earlier blocks) ---------------------------


def test_worker_shuts_down_cleanly_on_camera_fault_mid_stream(monkeypatch) -> None:
    tracker, _cursor, controller = _make(monkeypatch)
    for _ in range(5):
        tracker.feed([_hand(0.5, 0.55, "point")])
    tracker.raise_after(gd.CameraUnavailable("камера пропала во время работы"))
    controller.start()
    _wait_stopped(controller)
    assert "камера пропала" in (controller.last_error() or "")


def test_sustained_hand_loss_pulses_cursor_and_announces_once(monkeypatch) -> None:
    monkeypatch.setattr(gd, "HAND_LOST_ALERT_FRAMES", 20)
    tracker, _cursor, controller = _make(monkeypatch)
    pulses: list[int] = []
    says: list[str] = []
    monkeypatch.setattr(gd.cursor_zoom, "pulse", lambda *a, **k: pulses.append(1))
    controller._announce = says.append
    for _ in range(6):
        tracker.feed([_hand(0.5, 0.55, "point")])
    for _ in range(60):
        tracker.feed([])                       # sustained loss
    controller.start()
    try:
        _pump(tracker, 66)
    finally:
        controller.stop()
    assert len(pulses) == 1
    assert len([s for s in says if "потеряла руку" in s]) == 1


def test_physical_mouse_override_does_not_lurch_on_resume(monkeypatch) -> None:
    monkeypatch.setattr(gd, "PHYSICAL_MOUSE_OVERRIDE_SECONDS", 0.05)
    tracker, cursor, controller = _make(monkeypatch, fps=200)
    for _ in range(20):
        tracker.feed([_hand(0.5, 0.55, "point")])
    controller.start()
    try:
        _pump(tracker, 18)
        cursor.arm_physical_move()
        for _ in range(30):
            tracker.feed([_hand(0.5, 0.55, "point")])
        _pump(tracker, 50)
    finally:
        controller.stop()
    # after the override ends the cursor resumes at the mapped point, no fling
    assert cursor.moves


def test_calibration_can_be_cancelled_mid_run(monkeypatch) -> None:
    tracker, _cursor, controller = _make(monkeypatch, fps=200)
    for _ in range(20):
        tracker.feed([_hand(0.5, 0.55, "point")])
    controller.start()
    try:
        _pump(tracker, 5)
        assert controller.request_recalibration() is True
        for _ in range(120):
            tracker.feed([_hand(0.5, 0.55, "point")])
        _wait_for(lambda: gd.overlay_state.calibration is not None)
        assert controller.cancel_calibration() is True
        for _ in range(120):
            tracker.feed([_hand(0.5, 0.55, "point")])
        _wait_for(lambda: gd.overlay_state.calibration is None)
    finally:
        controller.stop()
