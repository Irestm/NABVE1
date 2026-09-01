from __future__ import annotations

import math

from modules.gesture_control.config import DEFAULT_FIST_RATIO, DEFAULT_OPEN_PALM_RATIO
from modules.gesture_control.hand_tracker import Landmarks

# MediaPipe hand landmark indices.
_WRIST = 0
_THUMB_TIP = 4
_INDEX_TIP = 8
_MIDDLE_TIP = 12
_MIDDLE_MCP = 9  # base of the middle finger — a stable "hand centre" proxy

# Non-thumb fingers: (tip, proximal-interphalangeal joint).
_FINGERS = ((8, 6), (12, 10), (16, 14), (20, 18))


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    return sorted(values)[len(values) // 2]


def _finger_ratios(hand: Landmarks) -> list[float]:
    """Per non-thumb finger: tip-distance-from-wrist over PIP-distance-from-
    wrist. >1 = extended, <1 = curled in. Scale-invariant."""
    wrist = hand[_WRIST]
    return sorted(
        _distance(hand[tip], wrist) / max(_distance(hand[pip], wrist), 1e-4)
        for tip, pip in _FINGERS
    )


def fist_score(hand: Landmarks) -> float:
    """How closed the hand is: the *largest* of the four finger ratios —
    i.e. how extended the least-curled finger is. A tight fist is ~0.8 or
    below (every finger curled), a relaxed/pointing hand ~1.4+, a spread
    palm ~2. Replaces the old thumb-index pinch, which was too small to
    read reliably ("жест пальцами слишком мелкий")."""
    return _finger_ratios(hand)[-1]


def is_fist(hand: Landmarks, threshold: float = DEFAULT_FIST_RATIO) -> bool:
    return fist_score(hand) <= threshold


def open_palm_score(hand: Landmarks) -> float:
    """How open the hand is: the 3rd-largest finger ratio — the value at/
    above which at least three fingers are extended. Fist ~1.0 or below,
    spread palm ~1.3+."""
    return _finger_ratios(hand)[1]


def is_open_palm(hand: Landmarks, ratio_threshold: float = DEFAULT_OPEN_PALM_RATIO) -> bool:
    """A whole open hand (3+ non-thumb fingers extended). A pointing hand
    (only the index out) fails this, so it can't be mistaken for a swipe
    while the user is just aiming the cursor. The threshold is personalised
    by the calibration wizard."""
    return open_palm_score(hand) >= ratio_threshold


def _hand_scale(hand: Landmarks) -> float:
    """Wrist -> middle-knuckle distance: a stable size normaliser (the palm
    length doesn't change when fingers curl or the hand rotates in plane)."""
    return max(_distance(hand[_WRIST], hand[_MIDDLE_MCP]), 1e-4)


_INDEX_MCP = 5
_INDEX_PIP = 6


def index_tip(hand: Landmarks) -> tuple[float, float]:
    """A "virtual" index fingertip: the direction of the finger taken from
    its two most stable joints (MCP 5 -> PIP 6) and extended forward to
    roughly where the tip is. The real tip (landmark 8) is the noisiest of
    the 21 points — when the finger points sideways MediaPipe loses it and
    snaps it back onto the middle phalanx, so the cursor stops registering
    motion. MCP and PIP stay put through that, so this tracks smoothly.
    The dispatcher freezes the cursor delta as soon as a click signal starts
    closing, so the arc into a fist / pinch never reaches the pointer."""
    mcp, pip = hand[_INDEX_MCP], hand[_INDEX_PIP]
    return (pip[0] + (pip[0] - mcp[0]) * 1.1, pip[1] + (pip[1] - mcp[1]) * 1.1)


def pinch3_spread(hand: Landmarks) -> float:
    """How tightly the thumb, index and middle fingertips are clustered,
    normalised by hand size. A deliberate 3-finger pinch ("OK"/"щепка")
    collapses this toward zero; any pointing / open / fist pose keeps it
    well above. Three tips (not two) so noise on any one is averaged out and
    MediaPipe has a bigger feature to lock onto — the old 2-finger pinch
    failed mostly to motion blur, now fixed by the short shutter. This is a
    different signal from fist_score (different landmarks), which is why it
    can separate a click even when fist_score's open/closed ranges overlap."""
    tips = (hand[_THUMB_TIP], hand[_INDEX_TIP], hand[_MIDDLE_TIP])
    cx = sum(t[0] for t in tips) / 3.0
    cy = sum(t[1] for t in tips) / 3.0
    spread = sum(math.hypot(t[0] - cx, t[1] - cy) for t in tips) / 3.0
    return spread / _hand_scale(hand)


def pinch2_gap(hand: Landmarks) -> float:
    """Thumb-tip to index-tip distance, hand-size normalised — logged next
    to pinch3_spread so the diagnostics show which separates better."""
    return _distance(hand[_THUMB_TIP], hand[_INDEX_TIP]) / _hand_scale(hand)


def _convex_hull_area(points: list[tuple[float, float]]) -> float:
    """Area of the convex hull of a point set (monotone-chain + shoelace).
    Pure Python, fine for 21 points."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return 0.0

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    area = 0.0
    for i in range(len(hull)):
        x1, y1 = hull[i]
        x2, y2 = hull[(i + 1) % len(hull)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def hull_compactness(hand: Landmarks) -> float:
    """Convex-hull area of all 21 landmarks over hand_size^2. A fist or a
    pinch collapses the hull toward the palm; an open or pointing hand keeps
    it large. Because it sums over every point, one glitchy fingertip barely
    moves it — steadier than any 2-point distance for the click decision."""
    scale = _hand_scale(hand)
    return _convex_hull_area(list(hand)) / (scale * scale)


def curled_finger_count(hand: Landmarks) -> int:
    """How many of the four non-thumb fingers are curled (tip nearer the
    wrist than that finger's PIP joint). A discrete 0-4 fist signal, robust
    where the continuous fist_score ratio is not — for the diagnostics."""
    wrist = hand[_WRIST]
    return sum(
        1
        for tip, pip in _FINGERS
        if _distance(hand[tip], wrist) < _distance(hand[pip], wrist)
    )


def hand_centre(hand: Landmarks) -> tuple[float, float]:
    """The point the cursor follows: the midpoint of the wrist and the
    middle-finger knuckle — the hand's rigid base. It does not move when the
    fingers curl, so forming a fist (to click) can't drag the pointer off
    target."""
    wrist, mcp = hand[_WRIST], hand[_MIDDLE_MCP]
    return ((wrist[0] + mcp[0]) / 2, (wrist[1] + mcp[1]) / 2)


def two_hand_spread(hand1: Landmarks, hand2: Landmarks) -> float:
    return _distance(hand_centre(hand1), hand_centre(hand2))


def two_hand_spread_delta(
    hand1: Landmarks, hand2: Landmarks, previous_distance: float | None
) -> tuple[float, float]:
    """Returns (current_spread, delta_since_previous). Positive delta = hands
    moving apart (zoom in), negative = together (zoom out); 0 on the first
    frame a second hand appears."""
    current = two_hand_spread(hand1, hand2)
    if previous_distance is None:
        return current, 0.0
    return current, current - previous_distance


def swipe_direction(
    x_history: list[float],
    y_history: list[float],
    min_dx: float,
    max_dy_ratio: float,
) -> int:
    """An open-palm horizontal swipe across the recent hand-centre history:
    +1 = swiped right, -1 = left, 0 = no swipe. The travel must clear
    `min_dx` and stay mostly horizontal (|dy| <= |dx| * max_dy_ratio). The
    mirrored frame means "hand to the user's right" -> +1."""
    if len(x_history) < 2 or len(y_history) < 2:
        return 0
    dx = x_history[-1] - x_history[0]
    dy = y_history[-1] - y_history[0]
    if abs(dx) < min_dx or abs(dy) > abs(dx) * max_dy_ratio:
        return 0
    return 1 if dx > 0 else -1
