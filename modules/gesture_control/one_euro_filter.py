from __future__ import annotations

import math

from modules.gesture_control.config import (
    ONE_EURO_BETA,
    ONE_EURO_D_CUTOFF,
    ONE_EURO_MIN_CUTOFF,
)


def _median3(values: list[float]) -> float:
    return sorted(values)[len(values) // 2]


def _alpha(cutoff: float, dt: float) -> float:
    tau = 1.0 / (2.0 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class OneEuroFilter:
    """The 1€ (One-Euro) filter on a single (x, y) point — the standard
    filter for real-time hand / gaze pointing: heavy smoothing when the hand
    is still, near-passthrough when it moves deliberately, with minimal lag.

    A median-of-3 prefilter drops single-frame landmark spikes before the
    filter runs. `min_cutoff` (Hz) is the low-pass cutoff at rest (lower =
    steadier, more lag) and is tuned per user by the calibration wizard;
    `beta` raises the cutoff in proportion to hand speed. Every update()
    needs a real, increasing timestamp in seconds.
    """

    def __init__(
        self,
        min_cutoff: float = ONE_EURO_MIN_CUTOFF,
        beta: float = ONE_EURO_BETA,
        d_cutoff: float = ONE_EURO_D_CUTOFF,
    ) -> None:
        self._min_cutoff = max(0.05, min_cutoff)
        self._beta = beta
        self._d_cutoff = d_cutoff
        self._window: list[tuple[float, float]] = []
        self._x_prev: tuple[float, float] | None = None
        self._dx_prev = (0.0, 0.0)
        self._t_prev: float | None = None

    def set_min_cutoff(self, min_cutoff: float) -> None:
        self._min_cutoff = max(0.05, min_cutoff)

    def update(self, point: tuple[float, float], timestamp: float) -> tuple[float, float]:
        self._window.append(point)
        if len(self._window) > 3:
            self._window.pop(0)
        point = (
            _median3([p[0] for p in self._window]),
            _median3([p[1] for p in self._window]),
        )

        if self._x_prev is None or self._t_prev is None:
            self._x_prev = point
            self._t_prev = timestamp
            return point

        dt = timestamp - self._t_prev
        if dt <= 0:
            dt = 1.0 / 30.0
        self._t_prev = timestamp

        a_d = _alpha(self._d_cutoff, dt)
        out: list[float] = []
        dx_new: list[float] = []
        for axis in (0, 1):
            raw_dx = (point[axis] - self._x_prev[axis]) / dt
            edx = self._dx_prev[axis] + a_d * (raw_dx - self._dx_prev[axis])
            dx_new.append(edx)
            cutoff = self._min_cutoff + self._beta * abs(edx)
            a = _alpha(cutoff, dt)
            out.append(self._x_prev[axis] + a * (point[axis] - self._x_prev[axis]))
        self._dx_prev = (dx_new[0], dx_new[1])
        self._x_prev = (out[0], out[1])
        return self._x_prev

    def reset(self) -> None:
        self._window.clear()
        self._x_prev = None
        self._dx_prev = (0.0, 0.0)
        self._t_prev = None
