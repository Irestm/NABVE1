from __future__ import annotations

import math

from modules.gesture_control.bone_fit import _PARENT, BoneModel
from modules.gesture_control.config import BONE_SCAN_FRAMES


def _hand(spread: float = 1.0) -> list[tuple[float, float]]:
    """A plausible 21-point hand: wrist at origin, each bone one unit long
    down its chain, scaled by `spread`."""
    pts: list[tuple[float, float]] = [(0.0, 0.0)] * 21
    for i in range(1, 21):
        p = _PARENT[i]
        pts[i] = (pts[p][0], pts[p][1] - 0.05 * spread)
    return pts


def test_not_ready_before_the_scan_completes() -> None:
    model = BoneModel()
    for _ in range(BONE_SCAN_FRAMES - 1):
        model.observe(_hand())
    assert model.ready is False
    assert model.fit(_hand(2.0)) == _hand(2.0)  # passthrough while scanning


def test_ready_after_the_scan_and_fit_enforces_bone_lengths() -> None:
    model = BoneModel()
    for _ in range(BONE_SCAN_FRAMES):
        model.observe(_hand(1.0))
    assert model.ready is True

    # Feed a hand where one fingertip has "jumped" far away.
    bad = _hand(1.0)
    bad[8] = (5.0, 5.0)
    fitted = model.fit(bad)
    # The index-tip -> index-pip bone is pulled back to ~its learned length.
    learned = math.hypot(*(a - b for a, b in zip(_hand(1.0)[8], _hand(1.0)[7])))
    got = math.hypot(fitted[8][0] - fitted[7][0], fitted[8][1] - fitted[7][1])
    assert got < learned * 3  # nowhere near the blown-up 5,5 distance


def test_fit_leaves_a_clean_hand_almost_unchanged() -> None:
    model = BoneModel()
    for _ in range(BONE_SCAN_FRAMES):
        model.observe(_hand(1.0))
    clean = _hand(1.0)
    fitted = model.fit(clean)
    for (fx, fy), (cx, cy) in zip(fitted, clean):
        assert math.hypot(fx - cx, fy - cy) < 1e-3
