from __future__ import annotations

from dataclasses import dataclass, field

from core.logger import get_logger
from modules.gesture_control.config import DEFAULT_PINCH_THRESHOLD, GESTURE_PINCH_THRESHOLD_KEY
from modules.user_profile import service_layer as profile_service_layer
from modules.user_profile.uow import ProfileUnitOfWork

logger = get_logger(__name__)

# How many open→close→open cycles to collect before computing the threshold.
_REQUIRED_CYCLES = 3
# The personal pinch threshold sits this fraction of the way from the
# tightest pinch to the widest open seen during calibration.
_THRESHOLD_FRACTION = 0.4
# A pinch is "released" once the distance climbs back above this multiple of
# the running minimum — used only to segment the cycles during calibration.
_RELEASE_FACTOR = 1.8


@dataclass
class CalibrationSession:
    """Drives the "сожмите и разожмите пальцы три раза" flow. Feed it
    pinch_distance() every frame via observe(); it counts completed
    open/close cycles and, once it has enough, computes and persists the
    user's personal is_pinching threshold."""

    _samples: list[float] = field(default_factory=list)
    _cycles: int = 0
    _in_pinch: bool = False
    _cycle_min: float = float("inf")
    done: bool = False
    threshold: float | None = None

    @property
    def cycles_done(self) -> int:
        return self._cycles

    def observe(self, distance: float) -> None:
        if self.done:
            return
        self._samples.append(distance)
        running_min = min(self._samples)

        if not self._in_pinch and distance <= running_min * 1.15:
            self._in_pinch = True
            self._cycle_min = distance
        elif self._in_pinch:
            self._cycle_min = min(self._cycle_min, distance)
            if distance >= self._cycle_min * _RELEASE_FACTOR:
                self._in_pinch = False
                self._cycles += 1
                if self._cycles >= _REQUIRED_CYCLES:
                    self._finish()

    def _finish(self) -> None:
        tight = min(self._samples)
        wide = max(self._samples)
        span = wide - tight
        self.threshold = tight + span * _THRESHOLD_FRACTION if span > 1e-4 else DEFAULT_PINCH_THRESHOLD
        self.done = True
        logger.info(
            "Gesture calibration done: tight=%.4f wide=%.4f threshold=%.4f", tight, wide, self.threshold
        )

    def persist(self) -> float:
        value = self.threshold if self.threshold is not None else DEFAULT_PINCH_THRESHOLD
        profile_service_layer.set_fact(ProfileUnitOfWork(), GESTURE_PINCH_THRESHOLD_KEY, f"{value:.5f}")
        return value


def load_threshold() -> float:
    stored = profile_service_layer.get_fact(ProfileUnitOfWork(), GESTURE_PINCH_THRESHOLD_KEY)
    try:
        return float(stored) if stored else DEFAULT_PINCH_THRESHOLD
    except ValueError:
        return DEFAULT_PINCH_THRESHOLD
