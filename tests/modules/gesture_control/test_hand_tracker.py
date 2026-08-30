from __future__ import annotations

from modules.gesture_control.config import HAND_BBOX_MAX
from modules.gesture_control.hand_tracker import _looks_like_hand

_WRIST = (0.5, 0.72)


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
