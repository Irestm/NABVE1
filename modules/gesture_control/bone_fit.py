from __future__ import annotations

import math

from modules.gesture_control.config import BONE_FIT_BLEND, BONE_SCAN_FRAMES
from modules.gesture_control.hand_tracker import Landmarks

# MediaPipe hand skeleton: parent landmark of each of the 21 points. Every
# parent index is lower than its child, so a single forward pass fits the
# whole hand.
_PARENT = (
    -1,
    0, 1, 2, 3,        # thumb
    0, 5, 6, 7,        # index
    0, 9, 10, 11,      # middle
    0, 13, 14, 15,     # ring
    0, 17, 18, 19,     # pinky
)


def _unit(dx: float, dy: float) -> tuple[float, float] | None:
    d = math.hypot(dx, dy)
    if d < 1e-6:
        return None
    return dx / d, dy / d


class BoneModel:
    """Learns one hand's bone lengths from the first BONE_SCAN_FRAMES frames
    with a hand present, then rigid-fits every later frame: each bone is set
    to its learned length along the raw segment's direction. A landmark that
    jumps can no longer stretch its segment, so the derived click signals
    (which are all bone-length ratios / hull areas) stop spiking."""

    def __init__(self) -> None:
        self._samples: list[list[float]] = [[] for _ in _PARENT]
        self._lengths: list[float] = [0.0] * len(_PARENT)
        self._seen = 0
        self.ready = False

    def observe(self, hand: Landmarks) -> None:
        if self.ready or len(hand) < len(_PARENT):
            return
        for i in range(1, len(_PARENT)):
            p = _PARENT[i]
            self._samples[i].append(
                math.hypot(hand[i][0] - hand[p][0], hand[i][1] - hand[p][1])
            )
        self._seen += 1
        if self._seen >= BONE_SCAN_FRAMES:
            for i in range(1, len(_PARENT)):
                vals = sorted(self._samples[i])
                self._lengths[i] = vals[len(vals) // 2] if vals else 0.0
            self._samples = []
            self.ready = True

    def fit(self, hand: Landmarks) -> Landmarks:
        if not self.ready or len(hand) < len(_PARENT):
            return hand
        fitted: list[tuple[float, float]] = [hand[0]]
        for i in range(1, len(_PARENT)):
            p = _PARENT[i]
            parent = fitted[p]
            direction = _unit(hand[i][0] - hand[p][0], hand[i][1] - hand[p][1])
            if direction is None:
                fitted.append(parent)
                continue
            length = self._lengths[i]
            fx = parent[0] + direction[0] * length
            fy = parent[1] + direction[1] * length
            rx, ry = hand[i]
            # Blend raw -> rigid: gentle for small corrections (keeps natural
            # micro-motion), but snap fully once the raw point is a whole
            # bone-length or more off — that is a blowup, not real motion.
            err = math.hypot(rx - fx, ry - fy)
            blend = BONE_FIT_BLEND + (1.0 - BONE_FIT_BLEND) * min(
                err / max(length, 1e-6), 1.0
            )
            fitted.append((rx + (fx - rx) * blend, ry + (fy - ry) * blend))
        return fitted
