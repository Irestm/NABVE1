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


def test_fit_is_hand_scale_invariant() -> None:
    # F2: bone lengths are learned as a fraction of palm length, so the same
    # hand held 3x closer to the camera is not squashed back to the 1x size.
    model = BoneModel()
    for _ in range(BONE_SCAN_FRAMES):
        model.observe(_hand(1.0))
    big = _hand(3.0)
    fitted = model.fit(big)
    for (fx, fy), (cx, cy) in zip(fitted, big):
        assert math.hypot(fx - cx, fy - cy) < 1e-3


def test_fit_preserves_a_clean_curl() -> None:
    # F3: a rotated (curled) finger whose bones kept their length must pass
    # through — bone-fit fights stretching, not the real curl signal.
    model = BoneModel()
    for _ in range(BONE_SCAN_FRAMES):
        model.observe(_hand(1.0))
    curled = _hand(1.0)
    curled[6] = (0.05, -0.05)  # index bones rotate ~90 deg, each still 0.05 long
    curled[7] = (0.05, 0.0)
    curled[8] = (0.0, 0.0)
    fitted = model.fit(curled)
    for (fx, fy), (cx, cy) in zip(fitted, curled):
        assert math.hypot(fx - cx, fy - cy) < 1e-3


def test_scan_skips_grip_frames_but_still_completes_on_clean_ones() -> None:
    # F1: grip frames don't contribute samples, but a low-reading open hand
    # (never excluded by an absolute bar now) still drives the model ready.
    model = BoneModel()
    for _ in range(BONE_SCAN_FRAMES * 2):
        model.observe(_hand(1.0), skip=True)
    assert model.ready is False
    for _ in range(BONE_SCAN_FRAMES):
        model.observe(_hand(1.0), skip=False)
    assert model.ready is True


def test_scan_times_out_with_a_usable_minimum_when_grips_dominate() -> None:
    model = BoneModel()
    for i in range(BONE_SCAN_FRAMES * 3):
        model.observe(_hand(1.0), skip=(i % 4 != 0))  # only 1/4 clean
    assert model.ready is True
    assert model.scanned < BONE_SCAN_FRAMES  # readiness came from the timeout path
