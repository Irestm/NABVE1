from __future__ import annotations

import math

from modules.gesture_control.hand_tracker import Landmarks

# MediaPipe hand landmark indices used here.
_THUMB_TIP = 4
_INDEX_TIP = 8
_WRIST = 0
_MIDDLE_MCP = 9  # base of the middle finger — a stable "hand centre" proxy


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def pinch_distance(hand: Landmarks) -> float:
    """Normalized-coordinate distance between the thumb tip (4) and index
    fingertip (8). Compared against the user's calibrated threshold to
    decide a 'pinch'."""
    return _distance(hand[_THUMB_TIP], hand[_INDEX_TIP])


def is_pinching(distance: float, threshold: float) -> bool:
    return distance <= threshold


def hand_centre(hand: Landmarks) -> tuple[float, float]:
    """A steady reference point for a whole hand — midpoint of wrist and the
    middle-finger base, less noisy than any single fingertip."""
    wrist, mcp = hand[_WRIST], hand[_MIDDLE_MCP]
    return ((wrist[0] + mcp[0]) / 2, (wrist[1] + mcp[1]) / 2)


def two_hand_spread(hand1: Landmarks, hand2: Landmarks) -> float:
    """Current distance between the two hand centres (normalized units)."""
    return _distance(hand_centre(hand1), hand_centre(hand2))


def two_hand_spread_delta(
    hand1: Landmarks, hand2: Landmarks, previous_distance: float | None
) -> tuple[float, float]:
    """Returns (current_spread, delta_since_previous). Positive delta = hands
    moving apart (zoom in), negative = together (zoom out). `previous_distance`
    is None on the first frame a second hand appears, giving delta 0."""
    current = two_hand_spread(hand1, hand2)
    if previous_distance is None:
        return current, 0.0
    return current, current - previous_distance
