from __future__ import annotations

import pytest

from modules.gesture_control import gesture_recognizer as gr


def _flat_hand() -> list[tuple[float, float]]:
    return [(0.0, 0.0)] * 21


def test_pinch_ratio_is_scale_invariant() -> None:
    # Same finger geometry, hand twice as big in frame -> same ratio.
    small = _flat_hand()
    small[0] = (0.50, 0.50)  # wrist
    small[5] = (0.50, 0.40)  # index mcp  -> span 0.10
    small[4] = (0.50, 0.45)  # thumb tip
    small[8] = (0.50, 0.42)  # index tip  -> tip gap 0.03  -> ratio 0.3

    big = _flat_hand()
    big[0] = (0.50, 0.50)
    big[5] = (0.50, 0.30)  # span 0.20
    big[4] = (0.50, 0.40)
    big[8] = (0.50, 0.34)  # tip gap 0.06 -> ratio 0.3

    assert gr.pinch_ratio(small) == pytest.approx(0.3, abs=1e-6)
    assert gr.pinch_ratio(big) == pytest.approx(0.3, abs=1e-6)


def test_is_pinching_threshold() -> None:
    assert gr.is_pinching(0.30, 0.45) is True
    assert gr.is_pinching(0.60, 0.45) is False
    assert gr.is_pinching(0.45, 0.45) is True


def test_open_hand_has_a_large_ratio() -> None:
    hand = _flat_hand()
    hand[0] = (0.5, 0.6)
    hand[5] = (0.5, 0.4)  # span 0.2
    hand[4] = (0.3, 0.3)
    hand[8] = (0.7, 0.3)  # tips far apart -> ratio ~2
    assert gr.pinch_ratio(hand) > 1.0


def test_two_hand_spread_delta_first_frame_is_zero() -> None:
    h1, h2 = _flat_hand(), _flat_hand()
    h1[0] = h1[9] = (0.2, 0.5)
    h2[0] = h2[9] = (0.6, 0.5)
    current, delta = gr.two_hand_spread_delta(h1, h2, None)
    assert current == pytest.approx(0.4)
    assert delta == 0.0


def test_two_hand_spread_delta_sign() -> None:
    h1, h2 = _flat_hand(), _flat_hand()
    h1[0] = h1[9] = (0.2, 0.5)
    h2[0] = h2[9] = (0.7, 0.5)  # spread 0.5
    _, apart = gr.two_hand_spread_delta(h1, h2, 0.4)
    assert apart > 0
    h2[0] = h2[9] = (0.3, 0.5)  # spread 0.1
    _, together = gr.two_hand_spread_delta(h1, h2, 0.4)
    assert together < 0


def test_swipe_direction_right_and_left() -> None:
    xs, ys = [0.2, 0.35, 0.5], [0.5, 0.5, 0.5]
    assert gr.swipe_direction(xs, ys, min_dx=0.25, max_dy_ratio=0.6) == 1
    assert gr.swipe_direction(xs[::-1], ys, min_dx=0.25, max_dy_ratio=0.6) == -1


def test_swipe_direction_ignores_small_travel() -> None:
    assert gr.swipe_direction([0.4, 0.45], [0.5, 0.5], min_dx=0.25, max_dy_ratio=0.6) == 0


def test_swipe_direction_ignores_a_mostly_vertical_move() -> None:
    assert gr.swipe_direction([0.2, 0.5], [0.2, 0.6], min_dx=0.25, max_dy_ratio=0.6) == 0


def test_swipe_direction_needs_two_samples() -> None:
    assert gr.swipe_direction([0.5], [0.5], min_dx=0.25, max_dy_ratio=0.6) == 0


def test_median() -> None:
    assert gr.median([]) == 0.0
    assert gr.median([0.4]) == 0.4
    assert gr.median([0.9, 0.1, 0.5]) == 0.5
    assert gr.median([5.0, 0.2, 0.3]) == 0.3  # one spike ignored


def _open_hand() -> list[tuple[float, float]]:
    hand = _flat_hand()
    hand[0] = (0.5, 0.9)  # wrist
    for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
        hand[pip] = (0.5, 0.6)
        hand[tip] = (0.5, 0.3)  # tip well past the pip -> extended
    return hand


def test_is_open_palm_true_for_a_spread_hand() -> None:
    assert gr.is_open_palm(_open_hand()) is True


def test_is_open_palm_false_for_a_pointing_hand() -> None:
    hand = _open_hand()
    for tip, pip in ((12, 10), (16, 14), (20, 18)):  # curl all but the index
        hand[tip] = (0.5, 0.62)  # tip barely past pip -> not extended
    assert gr.is_open_palm(hand) is False


def test_is_open_palm_false_for_a_fist() -> None:
    hand = _flat_hand()
    hand[0] = (0.5, 0.9)
    for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
        hand[pip] = (0.5, 0.7)
        hand[tip] = (0.5, 0.75)  # tip closer to wrist than pip -> curled
    assert gr.is_open_palm(hand) is False
