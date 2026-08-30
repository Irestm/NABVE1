from __future__ import annotations

import pytest

from modules.gesture_control.one_euro_filter import OneEuroFilter


def _feed(f: OneEuroFilter, points, dt: float = 1 / 30):
    out = None
    t = 0.0
    for p in points:
        out = f.update(p, t)
        t += dt
    return out


def test_first_value_passes_through() -> None:
    f = OneEuroFilter()
    assert f.update((10.0, 20.0), 0.0) == (10.0, 20.0)


def test_still_hand_is_heavily_damped() -> None:
    f = OneEuroFilter(min_cutoff=1.0)
    out = _feed(f, [(0.0, 0.0)] * 3 + [(0.01, 0.0), (-0.01, 0.0)] * 6)
    assert abs(out[0]) < 0.006


def test_deliberate_move_tracks_close() -> None:
    f = OneEuroFilter(min_cutoff=1.2, beta=2.5)
    ramp = [(i * 0.05, 0.0) for i in range(14)]
    out = _feed(f, ramp)
    assert out[0] > ramp[-1][0] - 0.15


def test_lower_min_cutoff_smooths_more() -> None:
    calm = OneEuroFilter(min_cutoff=0.3)
    lively = OneEuroFilter(min_cutoff=2.0)
    jitter = [(0.0, 0.0)] * 2 + [(0.02, 0.0), (-0.02, 0.0)] * 5
    assert abs(_feed(calm, jitter)[0]) <= abs(_feed(lively, jitter)[0]) + 1e-9


def test_set_min_cutoff_takes_effect_live() -> None:
    f = OneEuroFilter(min_cutoff=2.0)
    f.set_min_cutoff(0.3)
    ref = OneEuroFilter(min_cutoff=0.3)
    jitter = [(0.0, 0.0)] * 2 + [(0.02, 0.0), (-0.02, 0.0)] * 5
    assert _feed(f, jitter)[0] == pytest.approx(_feed(ref, jitter)[0])


def test_reset_clears_state() -> None:
    f = OneEuroFilter()
    _feed(f, [(100.0, 100.0)] * 4)
    f.reset()
    assert f.update((1.0, 2.0), 0.0) == (1.0, 2.0)


def test_median_prefilter_rejects_a_single_frame_spike() -> None:
    f = OneEuroFilter()
    out = _feed(f, [(0.0, 0.0), (0.0, 0.0), (9.0, 9.0)])
    assert out[0] < 0.5 and out[1] < 0.5
