from __future__ import annotations

import pytest

from modules.gesture_control import gesture_recognizer as gr


def _flat_hand() -> list[tuple[float, float]]:
    return [(0.0, 0.0)] * 21


def _fist_hand() -> list[tuple[float, float]]:
    hand = _flat_hand()
    hand[0] = (0.5, 0.9)  # wrist
    for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
        hand[pip] = (0.5, 0.7)
        hand[tip] = (0.5, 0.78)  # tip curled back toward the wrist
    return hand


def test_fist_score_low_for_a_closed_hand_high_for_open() -> None:
    assert gr.fist_score(_fist_hand()) < 1.0
    assert gr.fist_score(_open_hand()) > 1.5


def test_fist_score_is_the_least_curled_finger() -> None:
    hand = _fist_hand()
    hand[8] = (0.5, 0.3)  # one finger sticks out
    # fist_score = max ratio, so it reflects that extended finger
    assert gr.fist_score(hand) > 1.5


def test_is_fist_threshold() -> None:
    assert gr.is_fist(_fist_hand(), threshold=1.0) is True
    assert gr.is_fist(_open_hand(), threshold=1.0) is False


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


def test_open_palm_score_is_third_largest_extension_ratio() -> None:
    hand = _open_hand()  # all four fingers ratio 2.0
    assert gr.open_palm_score(hand) == pytest.approx(2.0)


def test_is_open_palm_threshold_is_configurable() -> None:
    hand = _open_hand()  # score 2.0
    assert gr.is_open_palm(hand, ratio_threshold=1.5) is True
    assert gr.is_open_palm(hand, ratio_threshold=2.5) is False


def _spread_hand() -> list[tuple[float, float]]:
    """A hand whose 21 points cover a wide area — an open, splayed palm."""
    hand = _flat_hand()
    hand[0] = (0.5, 0.9)  # wrist
    hand[9] = (0.5, 0.6)  # middle knuckle -> hand_scale ~0.3
    spots = [
        (0.20, 0.30), (0.30, 0.20), (0.40, 0.15), (0.50, 0.12),
        (0.60, 0.15), (0.70, 0.20), (0.80, 0.30),
    ]
    for i, xy in zip(range(1, 21), spots * 3):
        if i != 9:
            hand[i] = xy
    return hand


def test_hull_compactness_large_for_open_small_for_pinch() -> None:
    open_hand = _spread_hand()
    pinch = _spread_hand()
    for i in range(1, 21):  # collapse every finger onto the palm
        if i != 9:
            pinch[i] = (0.5, 0.62)
    assert gr.hull_compactness(open_hand) > gr.hull_compactness(pinch) * 3


def test_hull_compactness_is_scale_invariant() -> None:
    hand = _spread_hand()
    bigger = [(x * 2, y * 2) for x, y in hand]
    assert gr.hull_compactness(hand) == pytest.approx(gr.hull_compactness(bigger), rel=1e-6)


def test_pinch2_gap_small_when_thumb_meets_index() -> None:
    hand = _spread_hand()
    hand[4] = (0.50, 0.30)
    hand[8] = (0.51, 0.31)
    assert gr.pinch2_gap(hand) < 0.2


def test_index_tip_extrapolates_along_the_finger_from_stable_joints() -> None:
    hand = _spread_hand()
    hand[5] = (0.50, 0.50)   # MCP
    hand[6] = (0.50, 0.40)   # PIP, 0.1 further along -y
    hand[8] = (0.99, 0.99)   # a glitched raw tip that must be ignored
    vx, vy = gr.index_tip(hand)
    assert vx == pytest.approx(0.50)
    assert vy == pytest.approx(0.40 - 0.10 * 1.1)  # projected past the PIP, away from the MCP


def test_index_tip_follows_the_finger_swinging_sideways() -> None:
    left = _spread_hand()
    left[5], left[6] = (0.50, 0.50), (0.45, 0.42)
    right = _spread_hand()
    right[5], right[6] = (0.50, 0.50), (0.58, 0.42)
    assert gr.index_tip(right)[0] > gr.index_tip(left)[0]  # tracks the swing
