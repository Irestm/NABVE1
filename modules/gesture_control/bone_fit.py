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


def _hand_scale(hand: Landmarks) -> float:
    """Wrist (0) -> middle-knuckle (9) distance — the palm-length size
    normaliser. Bone lengths are learned and re-applied as a fraction of
    this, so moving the hand nearer/farther from the camera (which scales
    every landmark) doesn't leave the rigid skeleton the wrong size and
    drift the tracked point."""
    return math.hypot(hand[9][0] - hand[0][0], hand[9][1] - hand[0][1]) or 1e-6


class BoneModel:
    """Learns one hand's bone lengths (as fractions of palm length) from the
    first frames with an OPEN hand present, then rigid-fits every later
    frame: each bone is set to its learned length along the raw segment's
    direction, scaled to the current frame's palm length. A landmark that
    jumps can no longer stretch its segment, so the tracked point / derived
    signals stop spiking."""

    def __init__(self) -> None:
        self._samples: list[list[float]] = [[] for _ in _PARENT]
        self._lengths: list[float] = [0.0] * len(_PARENT)  # fraction of palm length
        self._seen = 0   # frames offered
        self._good = 0   # frames actually sampled (not a grip)
        self.ready = False

    @property
    def scanned(self) -> int:
        """Clean (non-grip) frames sampled so far — for the ready log line."""
        return self._good

    def observe(self, hand: Landmarks, skip: bool = False) -> None:
        """Feed one frame. `skip=True` (an active pinch/fist) still counts
        toward the timeout but its bone lengths are NOT sampled — a curled
        finger reads short and would bias the learned length."""
        if self.ready or len(hand) < len(_PARENT):
            return
        self._seen += 1
        if not skip:
            scale = _hand_scale(hand)
            for i in range(1, len(_PARENT)):
                p = _PARENT[i]
                self._samples[i].append(
                    math.hypot(hand[i][0] - hand[p][0], hand[i][1] - hand[p][1]) / scale
                )
            self._good += 1
        # Ready on enough clean samples, or — if grips kept dominating — on a
        # usable minimum after waiting 3x as long, so the fit can't stay
        # disabled forever for a user whose relaxed hand reads low.
        enough = self._good >= BONE_SCAN_FRAMES
        timed_out = self._seen >= BONE_SCAN_FRAMES * 3 and self._good >= BONE_SCAN_FRAMES // 3
        if enough or timed_out:
            for i in range(1, len(_PARENT)):
                vals = sorted(self._samples[i])
                self._lengths[i] = vals[len(vals) // 2] if vals else 0.0
            self._samples = []
            self.ready = True

    def fit(self, hand: Landmarks) -> Landmarks:
        if not self.ready or len(hand) < len(_PARENT):
            return hand
        scale = _hand_scale(hand)
        fitted: list[tuple[float, float]] = [hand[0]]
        for i in range(1, len(_PARENT)):
            p = _PARENT[i]
            parent = fitted[p]
            direction = _unit(hand[i][0] - hand[p][0], hand[i][1] - hand[p][1])
            if direction is None:
                fitted.append(parent)
                continue
            length = self._lengths[i] * scale
            fx = parent[0] + direction[0] * length
            fy = parent[1] + direction[1] * length
            rx, ry = hand[i]
            # Blend raw -> rigid: gentle for small corrections (keeps natural
            # micro-motion and the real finger-curl signal), but snap fully
            # once the raw point is a whole bone-length or more off — that is
            # a blowup, not real motion.
            err = math.hypot(rx - fx, ry - fy)
            blend = BONE_FIT_BLEND + (1.0 - BONE_FIT_BLEND) * min(
                err / max(length, 1e-6), 1.0
            )
            fitted.append((rx + (fx - rx) * blend, ry + (fy - ry) * blend))
        return fitted
