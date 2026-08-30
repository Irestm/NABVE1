from __future__ import annotations

import pytest

from modules.gesture_control.config import HAND_BBOX_MAX
from modules.gesture_control.hand_tracker import _OneEuroFilter, _looks_like_hand

_WRIST = (0.5, 0.72)


def _feed(f: _OneEuroFilter, points, dt: float = 1 / 30):
    out = None
    t = 0.0
    for p in points:
        out = f.update(p, t)
        t += dt
    return out


def _hand(knuckle_radii: tuple[float, float, float, float] = (0.15, 0.15, 0.15, 0.15)):
    """A 21-point landmark list where only what _looks_like_hand inspects is
    meaningful: the wrist (0) and the four knuckles (5, 9, 13, 17), placed at
    the given distances from the wrist. Everything else sits on the wrist."""
    pts = [_WRIST] * 21
    for idx, radius, x_off in zip((5, 9, 13, 17), knuckle_radii, (-0.045, -0.015, 0.015, 0.045)):
        pts[idx] = (_WRIST[0] + x_off, _WRIST[1] - radius)
    # a couple of fingertips out past the knuckles so the bbox is hand-sized
    pts[8] = (_WRIST[0], _WRIST[1] - max(knuckle_radii) - 0.12)
    pts[12] = (_WRIST[0] + 0.02, _WRIST[1] - max(knuckle_radii) - 0.12)
    return pts


def test_first_value_passes_through() -> None:
    f = _OneEuroFilter()
    assert f.update((10.0, 20.0), 0.0) == (10.0, 20.0)


def test_still_hand_is_heavily_damped() -> None:
    # A tiny tremra around a point: the filtered output stays far closer to
    # the mean than the raw jitter amplitude.
    f = _OneEuroFilter(min_cutoff=1.0)
    out = _feed(f, [(0.0, 0.0)] * 3 + [(0.01, 0.0), (-0.01, 0.0)] * 6)
    assert abs(out[0]) < 0.006


def test_deliberate_move_tracks_close() -> None:
    # A steady ramp: beta raises the cutoff with speed so the filter keeps
    # up to within ~a couple of frames of travel (median prefilter costs one).
    f = _OneEuroFilter(min_cutoff=1.2, beta=2.5)
    ramp = [(i * 0.05, 0.0) for i in range(14)]
    out = _feed(f, ramp)
    assert out[0] > ramp[-1][0] - 0.15


def test_lower_min_cutoff_smooths_more() -> None:
    calm = _OneEuroFilter(min_cutoff=0.3)
    lively = _OneEuroFilter(min_cutoff=2.0)
    jitter = [(0.0, 0.0)] * 2 + [(0.02, 0.0), (-0.02, 0.0)] * 5
    assert abs(_feed(calm, jitter)[0]) <= abs(_feed(lively, jitter)[0]) + 1e-9


def test_set_min_cutoff_takes_effect_live() -> None:
    f = _OneEuroFilter(min_cutoff=2.0)
    f.set_min_cutoff(0.3)
    ref = _OneEuroFilter(min_cutoff=0.3)
    jitter = [(0.0, 0.0)] * 2 + [(0.02, 0.0), (-0.02, 0.0)] * 5
    assert _feed(f, jitter)[0] == pytest.approx(_feed(ref, jitter)[0])


def test_reset_clears_state() -> None:
    f = _OneEuroFilter()
    _feed(f, [(100.0, 100.0)] * 4)
    f.reset()
    assert f.update((1.0, 2.0), 0.0) == (1.0, 2.0)


def test_median_prefilter_rejects_a_single_frame_spike() -> None:
    f = _OneEuroFilter()
    out = _feed(f, [(0.0, 0.0), (0.0, 0.0), (9.0, 9.0)])
    assert out[0] < 0.5 and out[1] < 0.5


def test_looks_like_hand_accepts_a_real_hand() -> None:
    assert _looks_like_hand(_hand((0.14, 0.15, 0.15, 0.16))) is True


def test_looks_like_hand_rejects_scattered_knuckles() -> None:
    # A face / torso false positive: "knuckles" at wildly inconsistent radii.
    assert _looks_like_hand(_hand((0.02, 0.40, 0.03, 0.38))) is False


def test_looks_like_hand_rejects_a_frame_filling_blob() -> None:
    pts = [(0.02, 0.02)] * 21
    pts[10] = (0.02 + HAND_BBOX_MAX + 0.05, 0.9)  # bbox span well over the max
    assert _looks_like_hand(pts) is False


def test_looks_like_hand_rejects_vanishing_noise() -> None:
    assert _looks_like_hand([(0.5, 0.5)] * 21) is False
