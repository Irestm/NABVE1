from __future__ import annotations

import math
from dataclasses import dataclass, field

from core.logger import get_logger
from modules.gesture_control.config import (
    CURSOR_DEADZONE_PX,
    DEADZONE_PX_MAX,
    DEADZONE_PX_MIN,
    DEFAULT_PINCH_RATIO,
    EMA_MIN_ALPHA,
    GESTURE_DEADZONE_PX_KEY,
    GESTURE_MIN_ALPHA_KEY,
    GESTURE_PINCH_THRESHOLD_KEY,
    JITTER_HIGH_PX,
    JITTER_LOW_PX,
    MIN_ALPHA_CEIL,
    MIN_ALPHA_FLOOR,
    STEADY_CALIBRATION_SAMPLES,
)
from modules.user_profile import service_layer as profile_service_layer
from modules.user_profile.uow import ProfileUnitOfWork

logger = get_logger(__name__)

_REQUIRED_CYCLES = 3
# Personal pinch threshold sits this fraction of the way from the tightest
# pinch ratio to the widest open ratio seen while calibrating.
_THRESHOLD_FRACTION = 0.45
# During calibration, a pinch counts as "released" once the ratio climbs
# back to this multiple of the running minimum.
_RELEASE_FACTOR = 1.6

_PHASE_STEADY = "steady"
_PHASE_PINCH = "pinch"

_PROMPT_STEADY = "Калибровка. Держите руку неподвижно перед камерой пару секунд."
_PROMPT_PINCH = "Теперь три раза медленно сожмите и разожмите большой и указательный пальцы."
_PROMPT_DONE = "Калибровка завершена."


def _lerp_min_alpha(jitter_px: float) -> float:
    span = max(JITTER_HIGH_PX - JITTER_LOW_PX, 1e-6)
    t = max(0.0, min(1.0, (jitter_px - JITTER_LOW_PX) / span))
    return round(MIN_ALPHA_CEIL + (MIN_ALPHA_FLOOR - MIN_ALPHA_CEIL) * t, 3)


@dataclass
class CalibrationSession:
    """Two-phase "калибровка": first the user holds the hand still while the
    fingertip tremor is measured (-> personal deadzone + resting smoothing),
    then the "сожмите и разожмите пальцы три раза" cycles set the pinch
    threshold. Feed observe() the pinch ratio and the raw fingertip point
    every frame; drain take_announcement() for the spoken prompts."""

    px_per_norm: float = 1000.0

    _phase: str = _PHASE_STEADY
    _steady_points: list[tuple[float, float]] = field(default_factory=list)
    _samples: list[float] = field(default_factory=list)
    _cycles: int = 0
    _in_pinch: bool = False
    _cycle_min: float = float("inf")
    _pending: str | None = _PROMPT_STEADY

    done: bool = False
    threshold: float | None = None
    deadzone_px: int | None = None
    min_alpha: float | None = None

    @property
    def cycles_done(self) -> int:
        return self._cycles

    def take_announcement(self) -> str | None:
        message, self._pending = self._pending, None
        return message

    def observe(self, ratio: float, point: tuple[float, float]) -> None:
        if self.done:
            return
        if self._phase == _PHASE_STEADY:
            self._observe_steady(point)
        else:
            self._observe_pinch(ratio)

    def _observe_steady(self, point: tuple[float, float]) -> None:
        self._steady_points.append(point)
        if len(self._steady_points) < STEADY_CALIBRATION_SAMPLES:
            return
        n = len(self._steady_points)
        mean_x = sum(p[0] for p in self._steady_points) / n
        mean_y = sum(p[1] for p in self._steady_points) / n
        rms = math.sqrt(
            sum((p[0] - mean_x) ** 2 + (p[1] - mean_y) ** 2 for p in self._steady_points) / n
        )
        jitter_px = rms * self.px_per_norm
        self.deadzone_px = int(
            max(DEADZONE_PX_MIN, min(DEADZONE_PX_MAX, round(jitter_px * 3 + 2)))
        )
        self.min_alpha = _lerp_min_alpha(jitter_px)
        self._phase = _PHASE_PINCH
        self._pending = _PROMPT_PINCH
        logger.info(
            "Gesture jitter calibration: rms=%.4f jitter=%.1fpx deadzone=%dpx min_alpha=%.3f",
            rms,
            jitter_px,
            self.deadzone_px,
            self.min_alpha,
        )

    def _observe_pinch(self, ratio: float) -> None:
        self._samples.append(ratio)
        running_min = min(self._samples)

        if not self._in_pinch and ratio <= running_min * 1.15:
            self._in_pinch = True
            self._cycle_min = ratio
        elif self._in_pinch:
            self._cycle_min = min(self._cycle_min, ratio)
            if ratio >= self._cycle_min * _RELEASE_FACTOR:
                self._in_pinch = False
                self._cycles += 1
                if self._cycles >= _REQUIRED_CYCLES:
                    self._finish_pinch()

    def _finish_pinch(self) -> None:
        tight = min(self._samples)
        wide = max(self._samples)
        span = wide - tight
        self.threshold = tight + span * _THRESHOLD_FRACTION if span > 1e-3 else DEFAULT_PINCH_RATIO
        self.done = True
        self._pending = _PROMPT_DONE
        logger.info(
            "Gesture pinch calibration done: tight=%.3f wide=%.3f threshold=%.3f",
            tight,
            wide,
            self.threshold,
        )

    def persist(self) -> tuple[float, int, float]:
        threshold = self.threshold if self.threshold is not None else DEFAULT_PINCH_RATIO
        deadzone = self.deadzone_px if self.deadzone_px is not None else CURSOR_DEADZONE_PX
        min_alpha = self.min_alpha if self.min_alpha is not None else EMA_MIN_ALPHA
        profile_service_layer.set_fact(
            ProfileUnitOfWork(), GESTURE_PINCH_THRESHOLD_KEY, f"{threshold:.4f}"
        )
        profile_service_layer.set_fact(ProfileUnitOfWork(), GESTURE_DEADZONE_PX_KEY, str(deadzone))
        profile_service_layer.set_fact(
            ProfileUnitOfWork(), GESTURE_MIN_ALPHA_KEY, f"{min_alpha:.3f}"
        )
        return threshold, deadzone, min_alpha


def _load_fact_float(key: str, default: float) -> float:
    stored = profile_service_layer.get_fact(ProfileUnitOfWork(), key)
    try:
        return float(stored) if stored else default
    except ValueError:
        return default


def load_threshold() -> float:
    return _load_fact_float(GESTURE_PINCH_THRESHOLD_KEY, DEFAULT_PINCH_RATIO)


def load_deadzone_px() -> int:
    return int(round(_load_fact_float(GESTURE_DEADZONE_PX_KEY, float(CURSOR_DEADZONE_PX))))


def load_min_alpha() -> float:
    return _load_fact_float(GESTURE_MIN_ALPHA_KEY, EMA_MIN_ALPHA)
