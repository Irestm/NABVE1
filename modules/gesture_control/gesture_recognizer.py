from __future__ import annotations

import math

from modules.gesture_control.config import DEFAULT_OPEN_PALM_RATIO
from modules.gesture_control.hand_tracker import Landmarks

# MediaPipe hand landmark indices.
_THUMB_TIP = 4
_INDEX_MCP = 5  # base knuckle of the index finger
_INDEX_TIP = 8
_WRIST = 0
_MIDDLE_MCP = 9  # base of the middle finger — a stable "hand centre" proxy

# Non-thumb fingers: (tip, proximal-interphalangeal joint).
_FINGERS = ((8, 6), (12, 10), (16, 14), (20, 18))


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    return sorted(values)[len(values) // 2]


def _hand_span(hand: Landmarks) -> float:
    """A per-hand length scale (wrist -> index knuckle) used to make the
    pinch measure independent of how big the hand looks in frame."""
    return max(_distance(hand[_WRIST], hand[_INDEX_MCP]), 1e-4)


def pinch_ratio(hand: Landmarks) -> float:
    """Thumb-tip↔index-tip distance as a fraction of the hand span. ~0.35
    when the fingers touch, ~1.0+ when the hand is open — scale-invariant,
    so it doesn't drift as the hand moves nearer/farther from the camera."""
    return _distance(hand[_THUMB_TIP], hand[_INDEX_TIP]) / _hand_span(hand)


def is_pinching(ratio: float, threshold: float) -> bool:
    return ratio <= threshold


def open_palm_score(hand: Landmarks) -> float:
    """How open the hand is: for each non-thumb finger, tip-distance-from-
    wrist over PIP-distance-from-wrist (>1 = extended). Returns the 3rd
    largest ratio — i.e. the value at/above which at least three fingers
    are extended. A fist is ~1.0 or below, a spread palm ~1.3+."""
    wrist = hand[_WRIST]
    ratios = sorted(
        _distance(hand[tip], wrist) / max(_distance(hand[pip], wrist), 1e-4)
        for tip, pip in _FINGERS
    )
    return ratios[1]  # 4 fingers -> index 1 is the 3rd largest


def is_open_palm(hand: Landmarks, ratio_threshold: float = DEFAULT_OPEN_PALM_RATIO) -> bool:
    """A whole open hand (3+ non-thumb fingers extended). A pointing hand
    (only the index out) fails this, so it can't be mistaken for a swipe
    while the user is just aiming the cursor. The threshold is personalised
    by the calibration wizard."""
    return open_palm_score(hand) >= ratio_threshold


def hand_centre(hand: Landmarks) -> tuple[float, float]:
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
