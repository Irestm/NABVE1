from __future__ import annotations

import pytest

from modules.gesture_control import gesture_recognizer as gr


def _flat_hand() -> list[tuple[float, float]]:
    # 21 landmarks, all at origin, then set the ones the recognizer reads.
    hand = [(0.0, 0.0)] * 21
    return hand


def test_pinch_distance_is_thumb_to_index() -> None:
    hand = _flat_hand()
    hand[4] = (0.5, 0.5)
    hand[8] = (0.5, 0.6)
    assert abs(gr.pinch_distance(hand) - 0.1) < 1e-9


def test_is_pinching_threshold() -> None:
    assert gr.is_pinching(0.03, 0.05) is True
    assert gr.is_pinching(0.08, 0.05) is False
    assert gr.is_pinching(0.05, 0.05) is True


def test_hand_centre_is_midpoint_of_wrist_and_middle_mcp() -> None:
    hand = _flat_hand()
    hand[0] = (0.2, 0.2)
    hand[9] = (0.4, 0.6)
    cx, cy = gr.hand_centre(hand)
    assert cx == pytest.approx(0.3)
    assert cy == pytest.approx(0.4)


def test_two_hand_spread_delta_first_frame_is_zero() -> None:
    h1, h2 = _flat_hand(), _flat_hand()
    h1[0] = h1[9] = (0.2, 0.5)
    h2[0] = h2[9] = (0.6, 0.5)
    current, delta = gr.two_hand_spread_delta(h1, h2, None)
    assert abs(current - 0.4) < 1e-9
    assert delta == 0.0


def test_two_hand_spread_delta_positive_when_hands_move_apart() -> None:
    h1, h2 = _flat_hand(), _flat_hand()
    h1[0] = h1[9] = (0.2, 0.5)
    h2[0] = h2[9] = (0.7, 0.5)  # spread now 0.5
    current, delta = gr.two_hand_spread_delta(h1, h2, 0.4)
    assert abs(current - 0.5) < 1e-9
    assert abs(delta - 0.1) < 1e-9


def test_two_hand_spread_delta_negative_when_hands_come_together() -> None:
    h1, h2 = _flat_hand(), _flat_hand()
    h1[0] = h1[9] = (0.4, 0.5)
    h2[0] = h2[9] = (0.6, 0.5)  # spread 0.2
    _, delta = gr.two_hand_spread_delta(h1, h2, 0.4)
    assert delta < 0
