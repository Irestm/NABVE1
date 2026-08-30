from __future__ import annotations

import pytest

from modules.gesture_control.config import (
    EMA_MAX_ALPHA,
    EMA_MIN_ALPHA,
    HAND_BBOX_MAX,
)
from modules.gesture_control.hand_tracker import _AdaptiveSmoother, _looks_like_hand


def test_first_value_passes_through() -> None:
    s = _AdaptiveSmoother()
    assert s.update((10.0, 20.0)) == (10.0, 20.0)


def test_fast_move_barely_lags() -> None:
    # A jump far larger than EMA_SPEED_FULL drives alpha to EMA_MAX_ALPHA.
    s = _AdaptiveSmoother()
    s.update((0.0, 0.0))
    x, _ = s.update((1.0, 0.0))
    assert x == pytest.approx(EMA_MAX_ALPHA, abs=1e-9)


def test_tiny_move_is_heavily_smoothed() -> None:
    # A sub-threshold twitch is blended with an alpha near EMA_MIN_ALPHA, so
    # the resting cursor barely moves ("очень дерганый" fix).
    s = _AdaptiveSmoother()
    s.update((0.0, 0.0))
    x, _ = s.update((0.001, 0.0))
    assert x < 0.001 * (EMA_MIN_ALPHA + 0.05)


def test_reset_clears_state() -> None:
    s = _AdaptiveSmoother()
    s.update((100.0, 100.0))
    s.reset()
    assert s.update((1.0, 2.0)) == (1.0, 2.0)


def test_median_prefilter_rejects_a_single_frame_spike() -> None:
    s = _AdaptiveSmoother()
    s.update((0.0, 0.0))
    s.update((0.0, 0.0))
    # One wild frame between two good ones: median of the 3-window ignores it.
    spiked = s.update((9.0, 9.0))
    assert spiked[0] < 0.5 and spiked[1] < 0.5


def test_lower_min_alpha_smooths_a_resting_hand_more() -> None:
    # Same sub-threshold twitch, calmer filter moves the point less.
    calm = _AdaptiveSmoother(min_alpha=0.03)
    twitchy = _AdaptiveSmoother(min_alpha=0.12)
    calm.update((0.0, 0.0))
    twitchy.update((0.0, 0.0))
    assert calm.update((0.001, 0.0))[0] < twitchy.update((0.001, 0.0))[0]


def test_set_min_alpha_takes_effect_live() -> None:
    s = _AdaptiveSmoother(min_alpha=0.12)
    s.update((0.0, 0.0))
    s.set_min_alpha(0.03)
    # Now behaves like a min_alpha=0.03 filter for a tiny move.
    ref = _AdaptiveSmoother(min_alpha=0.03)
    ref.update((0.0, 0.0))
    assert s.update((0.001, 0.0))[0] == pytest.approx(ref.update((0.001, 0.0))[0])


def _hand(width: float, height: float, cx: float = 0.5, cy: float = 0.5) -> list[tuple[float, float]]:
    # A cross of points that pins the bounding box to exactly width x height.
    return [
        (cx - width / 2, cy),
        (cx + width / 2, cy),
        (cx, cy - height / 2),
        (cx, cy + height / 2),
    ] * 5 + [(cx, cy)]


def test_looks_like_hand_accepts_a_normal_hand() -> None:
    assert _looks_like_hand(_hand(0.20, 0.24)) is True


def test_looks_like_hand_rejects_a_face_sized_blob() -> None:
    assert _looks_like_hand(_hand(HAND_BBOX_MAX + 0.1, HAND_BBOX_MAX + 0.1)) is False


def test_looks_like_hand_rejects_vanishing_noise() -> None:
    assert _looks_like_hand(_hand(0.01, 0.01)) is False


def test_looks_like_hand_rejects_an_extreme_aspect_ratio() -> None:
    assert _looks_like_hand(_hand(0.30, 0.02)) is False
