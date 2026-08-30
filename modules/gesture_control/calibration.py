from __future__ import annotations

import math
from dataclasses import dataclass, field

from core.logger import get_logger
from modules.gesture_control.config import (
    CURSOR_DEADZONE_PX,
    DEADZONE_PX_MAX,
    DEADZONE_PX_MIN,
    DEFAULT_OPEN_PALM_RATIO,
    DEFAULT_PINCH_RATIO,
    EMA_MIN_ALPHA,
    GESTURE_DEADZONE_PX_KEY,
    GESTURE_MIN_ALPHA_KEY,
    GESTURE_OPEN_PALM_RATIO_KEY,
    GESTURE_PINCH_THRESHOLD_KEY,
    GESTURE_SWIPE_MIN_DX_KEY,
    JITTER_HIGH_PX,
    JITTER_LOW_PX,
    MIN_ALPHA_CEIL,
    MIN_ALPHA_FLOOR,
    OPEN_PALM_RATIO_MAX,
    OPEN_PALM_RATIO_MIN,
    STEADY_CALIBRATION_SAMPLES,
    SWIPE_MIN_DX,
    SWIPE_MIN_DX_CEIL,
    SWIPE_MIN_DX_FLOOR,
)
from modules.gesture_control.gesture_recognizer import median
from modules.user_profile import service_layer as profile_service_layer
from modules.user_profile.uow import ProfileUnitOfWork

logger = get_logger(__name__)

_REQUIRED_REPS = 3

_PHASE_STEADY = "steady"
_PHASE_PINCH = "pinch"
_PHASE_OPEN_PALM = "open_palm"
_PHASE_SWIPE = "swipe"
_PHASE_DONE = "done"

_PROMPTS = {
    _PHASE_STEADY: "Калибровка. Держите руку неподвижно перед камерой пару секунд.",
    _PHASE_PINCH: "Теперь три раза медленно сожмите и разожмите большой и указательный пальцы.",
    _PHASE_OPEN_PALM: "Теперь три раза раскройте всю ладонь и снова сожмите в кулак.",
    _PHASE_SWIPE: "Теперь три раза проведите открытой ладонью влево и вправо.",
    _PHASE_DONE: "Калибровка завершена.",
}


@dataclass(frozen=True)
class CalibrationFrame:
    pinch_ratio: float
    open_palm_score: float
    raw_tip: tuple[float, float]
    palm_centre: tuple[float, float]


@dataclass(frozen=True)
class AppliedCalibration:
    pinch_threshold: float
    deadzone_px: int
    min_alpha: float
    open_palm_ratio: float
    swipe_min_dx: float


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _lerp_min_alpha(jitter_px: float) -> float:
    span = max(JITTER_HIGH_PX - JITTER_LOW_PX, 1e-6)
    t = _clamp((jitter_px - JITTER_LOW_PX) / span, 0.0, 1.0)
    return round(MIN_ALPHA_CEIL + (MIN_ALPHA_FLOOR - MIN_ALPHA_CEIL) * t, 3)


class _RepCounter:
    """Counts "do it N times" for a scalar signal that swings between a low
    and a high state. A rep = the value crosses the midpoint of its observed
    range into the gesture side and back out (with a hysteresis band).
    `active_high` picks which side is the gesture — pinch drives the ratio
    low, open palm drives the score high."""

    def __init__(self, active_high: bool, min_span: float) -> None:
        self._active_high = active_high
        self._min_span = min_span
        self._samples: list[float] = []
        self._in_gesture = False
        self.reps = 0

    def observe(self, value: float) -> None:
        self._samples.append(value)
        low, high = min(self._samples), max(self._samples)
        span = high - low
        if span < self._min_span:  # not enough range seen to know the two states apart
            return
        band = span * 0.15
        mid = (low + high) / 2
        if self._active_high:
            enter, leave = value >= mid + band, value <= mid - band
        else:
            enter, leave = value <= mid - band, value >= mid + band
        if not self._in_gesture and enter:
            self._in_gesture = True
        elif self._in_gesture and leave:
            self._in_gesture = False
            self.reps += 1

    def span(self) -> tuple[float, float]:
        return min(self._samples), max(self._samples)


@dataclass
class CalibrationSession:
    """The gesture wizard: STEADY (jitter) -> PINCH -> OPEN_PALM -> SWIPE,
    each gesture done three times, each deriving its own personal threshold.
    Feed it a CalibrationFrame every frame; drain take_announcement() for
    the spoken step prompts; call persist() once done."""

    px_per_norm: float = 1000.0

    _phase: str = _PHASE_STEADY
    _pending: str | None = _PROMPTS[_PHASE_STEADY]

    _steady_points: list[tuple[float, float]] = field(default_factory=list)
    _pinch: _RepCounter = field(
        default_factory=lambda: _RepCounter(active_high=False, min_span=0.25)
    )
    _open_palm: _RepCounter = field(
        default_factory=lambda: _RepCounter(active_high=True, min_span=0.12)
    )
    _swipe_xs: list[float] = field(default_factory=list)
    _swipe_dir: int = 0
    _swing_start_x: float = 0.0
    _swipe_travels: list[float] = field(default_factory=list)

    done: bool = False
    deadzone_px: int | None = None
    min_alpha: float | None = None
    pinch_threshold: float | None = None
    open_palm_ratio: float | None = None
    swipe_min_dx: float | None = None

    def take_announcement(self) -> str | None:
        message, self._pending = self._pending, None
        return message

    def _advance(self, phase: str) -> None:
        self._phase = phase
        self._pending = _PROMPTS[phase]
        if phase == _PHASE_DONE:
            self.done = True

    def observe(self, frame: CalibrationFrame) -> None:
        if self.done:
            return
        if self._phase == _PHASE_STEADY:
            self._observe_steady(frame.raw_tip)
        elif self._phase == _PHASE_PINCH:
            self._pinch.observe(frame.pinch_ratio)
            if self._pinch.reps >= _REQUIRED_REPS:
                self._finish_pinch()
        elif self._phase == _PHASE_OPEN_PALM:
            self._open_palm.observe(frame.open_palm_score)
            if self._open_palm.reps >= _REQUIRED_REPS:
                self._finish_open_palm()
        elif self._phase == _PHASE_SWIPE:
            self._observe_swipe(frame.palm_centre[0])

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
        self.deadzone_px = int(_clamp(round(jitter_px * 3 + 2), DEADZONE_PX_MIN, DEADZONE_PX_MAX))
        self.min_alpha = _lerp_min_alpha(jitter_px)
        logger.info(
            "Calibration STEADY: jitter=%.1fpx deadzone=%dpx min_alpha=%.3f",
            jitter_px,
            self.deadzone_px,
            self.min_alpha,
        )
        self._advance(_PHASE_PINCH)

    def _finish_pinch(self) -> None:
        tight, wide = self._pinch.span()
        span = wide - tight
        value = tight + span * 0.45 if span > 1e-3 else DEFAULT_PINCH_RATIO
        self.pinch_threshold = round(_clamp(value, 0.2, 0.75), 4)
        logger.info(
            "Calibration PINCH: tight=%.3f wide=%.3f threshold=%.3f",
            tight,
            wide,
            self.pinch_threshold,
        )
        self._advance(_PHASE_OPEN_PALM)

    def _finish_open_palm(self) -> None:
        low, high = self._open_palm.span()
        span = high - low
        value = low + span * 0.5 if span > 1e-3 else DEFAULT_OPEN_PALM_RATIO
        self.open_palm_ratio = round(_clamp(value, OPEN_PALM_RATIO_MIN, OPEN_PALM_RATIO_MAX), 3)
        logger.info(
            "Calibration OPEN_PALM: low=%.3f high=%.3f threshold=%.3f",
            low,
            high,
            self.open_palm_ratio,
        )
        self._advance(_PHASE_SWIPE)

    def _observe_swipe(self, x: float) -> None:
        self._swipe_xs.append(x)
        if len(self._swipe_xs) < 3:
            return
        velocity = self._swipe_xs[-1] - self._swipe_xs[-3]
        direction = 1 if velocity > 0.012 else (-1 if velocity < -0.012 else 0)
        if direction == 0:
            return
        if self._swipe_dir == 0:
            self._swipe_dir = direction
            self._swing_start_x = self._swipe_xs[-3]
        elif direction != self._swipe_dir:
            # x has already moved a couple frames back from the turning
            # point, so measure the finished swing from the extreme (~xs[-3]).
            turn_x = self._swipe_xs[-3]
            travel = abs(turn_x - self._swing_start_x)
            if travel >= 0.05:
                self._swipe_travels.append(travel)
            self._swipe_dir = direction
            self._swing_start_x = turn_x
        if len(self._swipe_travels) >= _REQUIRED_REPS:
            self._finish_swipe()

    def _finish_swipe(self) -> None:
        value = median(sorted(self._swipe_travels)) * 0.6
        self.swipe_min_dx = round(_clamp(value, SWIPE_MIN_DX_FLOOR, SWIPE_MIN_DX_CEIL), 3)
        logger.info(
            "Calibration SWIPE: travels=%s swipe_min_dx=%.3f",
            [round(t, 2) for t in self._swipe_travels],
            self.swipe_min_dx,
        )
        self._advance(_PHASE_DONE)

    def persist(self) -> AppliedCalibration:
        applied = AppliedCalibration(
            pinch_threshold=self.pinch_threshold
            if self.pinch_threshold is not None
            else DEFAULT_PINCH_RATIO,
            deadzone_px=self.deadzone_px if self.deadzone_px is not None else CURSOR_DEADZONE_PX,
            min_alpha=self.min_alpha if self.min_alpha is not None else EMA_MIN_ALPHA,
            open_palm_ratio=self.open_palm_ratio
            if self.open_palm_ratio is not None
            else DEFAULT_OPEN_PALM_RATIO,
            swipe_min_dx=self.swipe_min_dx if self.swipe_min_dx is not None else SWIPE_MIN_DX,
        )
        _set_fact(GESTURE_PINCH_THRESHOLD_KEY, f"{applied.pinch_threshold:.4f}")
        _set_fact(GESTURE_DEADZONE_PX_KEY, str(applied.deadzone_px))
        _set_fact(GESTURE_MIN_ALPHA_KEY, f"{applied.min_alpha:.3f}")
        _set_fact(GESTURE_OPEN_PALM_RATIO_KEY, f"{applied.open_palm_ratio:.3f}")
        _set_fact(GESTURE_SWIPE_MIN_DX_KEY, f"{applied.swipe_min_dx:.3f}")
        return applied


def _set_fact(key: str, value: str) -> None:
    profile_service_layer.set_fact(ProfileUnitOfWork(), key, value)


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


def load_open_palm_ratio() -> float:
    return _load_fact_float(GESTURE_OPEN_PALM_RATIO_KEY, DEFAULT_OPEN_PALM_RATIO)


def load_swipe_min_dx() -> float:
    return _load_fact_float(GESTURE_SWIPE_MIN_DX_KEY, SWIPE_MIN_DX)
