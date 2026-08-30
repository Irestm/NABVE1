from __future__ import annotations

import math

from modules.gesture_control.hand_tracker import Landmarks

# MediaPipe hand landmark indices.
_THUMB_TIP = 4
_INDEX_MCP = 5  # base knuckle of the index finger
_INDEX_TIP = 8
_WRIST = 0
_MIDDLE_MCP = 9  # base of the middle finger — a stable "hand centre" proxy


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


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
