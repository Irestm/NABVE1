from __future__ import annotations

from modules.gesture_control.hand_tracker import _EmaSmoother


def test_first_value_passes_through() -> None:
    s = _EmaSmoother(alpha=0.4)
    assert s.update((10.0, 20.0)) == (10.0, 20.0)


def test_smoothing_lags_toward_the_target() -> None:
    s = _EmaSmoother(alpha=0.5)
    s.update((0.0, 0.0))
    x, y = s.update((10.0, 10.0))
    assert x == 5.0 and y == 5.0
    x, y = s.update((10.0, 10.0))
    assert x == 7.5 and y == 7.5


def test_lower_alpha_smooths_more() -> None:
    slow, fast = _EmaSmoother(alpha=0.1), _EmaSmoother(alpha=0.9)
    slow.update((0.0, 0.0))
    fast.update((0.0, 0.0))
    assert fast.update((1.0, 0.0))[0] > slow.update((1.0, 0.0))[0]


def test_reset_clears_state() -> None:
    s = _EmaSmoother(alpha=0.5)
    s.update((100.0, 100.0))
    s.reset()
    assert s.update((1.0, 2.0)) == (1.0, 2.0)


def test_alpha_is_clamped() -> None:
    s = _EmaSmoother(alpha=5.0)
    s.update((0.0, 0.0))
    # clamped to 1.0 -> follows fully
    assert s.update((3.0, 4.0)) == (3.0, 4.0)
