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
    GESTURE_DEADZONE_PX_KEY,
    GESTURE_MIN_CUTOFF_KEY,
    GESTURE_OPEN_PALM_RATIO_KEY,
    GESTURE_PINCH_THRESHOLD_KEY,
    GESTURE_SWIPE_MIN_DX_KEY,
    GESTURE_ZONE_KEY,
    CALIBRATION_MAX_DARK_FRACTION,
    CALIBRATION_MIN_BRIGHTNESS,
    CORNER_CALIBRATION_SAMPLES,
    CORNER_ZONE_MIN_SPAN,
    CORNER_ZONE_PAD,
    JITTER_HIGH_PX,
    JITTER_LOW_PX,
    MIN_CUTOFF_CEIL,
    MIN_CUTOFF_FLOOR,
    ONE_EURO_MIN_CUTOFF,
    OPEN_PALM_RATIO_MAX,
    OPEN_PALM_RATIO_MIN,
    STEADY_CALIBRATION_SAMPLES,
    SWIPE_MIN_DX,
    SWIPE_MIN_DX_CEIL,
    SWIPE_MIN_DX_FLOOR,
)
from modules.user_profile import service_layer as profile_service_layer
from modules.user_profile.uow import ProfileUnitOfWork

logger = get_logger(__name__)

# Each gesture is demonstrated this many times; the wizard learns the
# threshold from the spread of those reps.
_REQUIRED_REPS = 5

_PHASE_STEADY = "steady"
_PHASE_PINCH = "pinch"
_PHASE_OPEN_PALM = "open_palm"
_PHASE_SWIPE = "swipe"
_PHASE_CORNERS = "corners"
_PHASE_DONE = "done"

_TOTAL_PHASES = 5

_PROMPTS = {
    _PHASE_STEADY: "Калибровка. Держите руку неподвижно перед камерой пару секунд.",
    _PHASE_PINCH: "Теперь пять раз медленно сожмите и разожмите большой и указательный пальцы.",
    _PHASE_OPEN_PALM: "Теперь пять раз раскройте всю ладонь и снова сожмите в кулак.",
    _PHASE_SWIPE: "Теперь пять раз проведите открытой ладонью влево и вправо.",
    _PHASE_CORNERS: "Теперь медленно обведите рукой четыре угла экрана.",
    _PHASE_DONE: "Калибровка завершена.",
}

# (phase_index, short label, short on-screen instruction)
_PHASE_META = {
    _PHASE_STEADY: (1, "Неподвижная рука", "Держите руку неподвижно перед камерой"),
    _PHASE_PINCH: (2, "Щипок", "Сожмите и разожмите большой и указательный пальцы"),
    _PHASE_OPEN_PALM: (3, "Ладонь", "Раскройте всю ладонь и снова сожмите в кулак"),
    _PHASE_SWIPE: (4, "Взмах ладонью", "Проведите открытой ладонью влево и вправо"),
    _PHASE_CORNERS: (5, "Углы экрана", "Медленно обведите рукой четыре угла экрана"),
}


@dataclass(frozen=True)
class CalibrationFrame:
    pinch_ratio: float
    open_palm_score: float
    raw_tip: tuple[float, float]
    palm_centre: tuple[float, float]
    brightness: float = -1.0  # mean pixel value of the source frame, -1 if unknown


@dataclass(frozen=True)
class CalibrationProgress:
    phase_index: int
    total_phases: int
    label: str
    instruction: str
    reps_done: int
    reps_target: int
    done: bool


@dataclass(frozen=True)
class AppliedCalibration:
    pinch_threshold: float
    deadzone_px: int
    min_cutoff: float
    open_palm_ratio: float
    swipe_min_dx: float
    zone_bounds: tuple[float, float, float, float] | None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _lerp_min_cutoff(jitter_px: float) -> float:
    """Steady hand (low jitter) -> MIN_CUTOFF_CEIL (lighter smoothing);
    shaky hand (high jitter) -> MIN_CUTOFF_FLOOR (heavier)."""
    span = max(JITTER_HIGH_PX - JITTER_LOW_PX, 1e-6)
    t = _clamp((jitter_px - JITTER_LOW_PX) / span, 0.0, 1.0)
    return round(MIN_CUTOFF_CEIL + (MIN_CUTOFF_FLOOR - MIN_CUTOFF_CEIL) * t, 3)


def _trimmed_mean(values: list[float]) -> float:
    """Mean after dropping the single lowest and highest sample (needs >=3)
    — a robust personal level that one bad rep can't skew."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) >= 3:
        ordered = ordered[1:-1]
    return sum(ordered) / len(ordered)


class _RepCounter:
    """Counts "do it N times" for a scalar signal that swings between a low
    and a high state, and records the extreme reached on each side. A rep =
    the value crosses the midpoint of its observed range into the gesture
    side and back out (with a hysteresis band). `active_high` picks which
    side is the gesture — pinch drives the ratio low, open palm the score
    high."""

    def __init__(self, active_high: bool, min_span: float) -> None:
        self._active_high = active_high
        self._min_span = min_span
        self._samples: list[float] = []
        self._in_gesture = False
        self._cur_extreme: float | None = None
        self._gesture_extremes: list[float] = []
        self._rest_extremes: list[float] = []
        self.reps = 0

    def observe(self, value: float) -> None:
        self._samples.append(value)
        low, high = min(self._samples), max(self._samples)
        span = high - low
        if span < self._min_span:  # not enough range seen to tell the two states apart
            return
        band = span * 0.15
        mid = (low + high) / 2
        if self._active_high:
            enter, leave = value >= mid + band, value <= mid - band
        else:
            enter, leave = value <= mid - band, value >= mid + band

        if self._cur_extreme is None:
            self._cur_extreme = value
        elif self._in_gesture == self._active_high:
            self._cur_extreme = max(self._cur_extreme, value)
        else:
            self._cur_extreme = min(self._cur_extreme, value)

        if not self._in_gesture and enter:
            self._rest_extremes.append(self._cur_extreme)
            self._in_gesture = True
            self._cur_extreme = value
        elif self._in_gesture and leave:
            self._gesture_extremes.append(self._cur_extreme)
            self._in_gesture = False
            self._cur_extreme = value
            self.reps += 1

    def gesture_level(self) -> float:
        return _trimmed_mean(self._gesture_extremes)

    def rest_level(self) -> float:
        if self._rest_extremes:
            return _trimmed_mean(self._rest_extremes)
        return max(self._samples) if self._active_high else min(self._samples)


@dataclass
class CalibrationSession:
    """The gesture wizard: STEADY (jitter) -> PINCH -> OPEN_PALM -> SWIPE,
    each gesture demonstrated five times, each deriving its own personal
    threshold. Feed it a CalibrationFrame every frame; drain
    take_announcement() for the spoken prompts and progress() for the
    on-screen wizard; call persist() once done."""

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
    _corner_pts: list[tuple[float, float]] = field(default_factory=list)

    done: bool = False
    aborted: bool = False
    abort_reason: str = ""
    _dark_frames: int = 0
    _total_frames: int = 0
    deadzone_px: int | None = None
    min_cutoff: float | None = None
    pinch_threshold: float | None = None
    open_palm_ratio: float | None = None
    swipe_min_dx: float | None = None
    zone_bounds: tuple[float, float, float, float] | None = None

    def take_announcement(self) -> str | None:
        message, self._pending = self._pending, None
        return message

    def progress(self) -> CalibrationProgress:
        if self._phase == _PHASE_DONE:
            return CalibrationProgress(
                _TOTAL_PHASES, _TOTAL_PHASES, "Готово", "Калибровка завершена",
                _REQUIRED_REPS, _REQUIRED_REPS, True,
            )
        index, label, instruction = _PHASE_META[self._phase]
        if self._phase == _PHASE_STEADY:
            done = len(self._steady_points) * _REQUIRED_REPS // max(STEADY_CALIBRATION_SAMPLES, 1)
        elif self._phase == _PHASE_PINCH:
            done = self._pinch.reps
        elif self._phase == _PHASE_OPEN_PALM:
            done = self._open_palm.reps
        elif self._phase == _PHASE_SWIPE:
            done = len(self._swipe_travels)
        else:
            done = len(self._corner_pts) * _REQUIRED_REPS // max(CORNER_CALIBRATION_SAMPLES, 1)
        return CalibrationProgress(
            index, _TOTAL_PHASES, label, instruction,
            min(_REQUIRED_REPS, done), _REQUIRED_REPS, False,
        )

    def _advance(self, phase: str) -> None:
        self._phase = phase
        self._pending = _PROMPTS[phase]
        if phase == _PHASE_DONE:
            self.done = True

    def observe(self, frame: CalibrationFrame) -> None:
        if self.done:
            return
        self._total_frames += 1
        if 0 <= frame.brightness < CALIBRATION_MIN_BRIGHTNESS:
            self._dark_frames += 1
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
        elif self._phase == _PHASE_CORNERS:
            self._observe_corners(frame.raw_tip)

    def _abort(self, reason: str) -> None:
        self.aborted = True
        self.abort_reason = reason
        self._pending = f"Калибровка отменена: {reason}."
        self._phase = _PHASE_DONE
        self.done = True

    def _observe_steady(self, point: tuple[float, float]) -> None:
        self._steady_points.append(point)
        if len(self._steady_points) < STEADY_CALIBRATION_SAMPLES:
            return
        if self._total_frames and self._dark_frames / self._total_frames > CALIBRATION_MAX_DARK_FRACTION:
            self._abort("слишком темно, добавьте света и повторите")
            return
        n = len(self._steady_points)
        mean_x = sum(p[0] for p in self._steady_points) / n
        mean_y = sum(p[1] for p in self._steady_points) / n
        rms = math.sqrt(
            sum((p[0] - mean_x) ** 2 + (p[1] - mean_y) ** 2 for p in self._steady_points) / n
        )
        jitter_px = rms * self.px_per_norm
        self.deadzone_px = int(_clamp(round(jitter_px * 3 + 2), DEADZONE_PX_MIN, DEADZONE_PX_MAX))
        self.min_cutoff = _lerp_min_cutoff(jitter_px)
        logger.info(
            "Calibration STEADY: jitter=%.1fpx deadzone=%dpx min_cutoff=%.2f",
            jitter_px,
            self.deadzone_px,
            self.min_cutoff,
        )
        self._advance(_PHASE_PINCH)

    def _finish_pinch(self) -> None:
        tight = self._pinch.gesture_level()  # trimmed mean of per-squeeze minima
        wide = self._pinch.rest_level()  # trimmed mean of the open-hand ratio
        span = wide - tight
        value = tight + span * 0.45 if span > 1e-3 else DEFAULT_PINCH_RATIO
        self.pinch_threshold = round(_clamp(value, 0.2, 0.75), 4)
        logger.info(
            "Calibration PINCH: squeezed=%.3f open=%.3f threshold=%.3f (%d reps)",
            tight,
            wide,
            self.pinch_threshold,
            self._pinch.reps,
        )
        self._advance(_PHASE_OPEN_PALM)

    def _finish_open_palm(self) -> None:
        high = self._open_palm.gesture_level()  # trimmed mean of per-spread maxima
        low = self._open_palm.rest_level()  # trimmed mean of the fist score
        span = high - low
        value = low + span * 0.5 if span > 1e-3 else DEFAULT_OPEN_PALM_RATIO
        self.open_palm_ratio = round(_clamp(value, OPEN_PALM_RATIO_MIN, OPEN_PALM_RATIO_MAX), 3)
        logger.info(
            "Calibration OPEN_PALM: fist=%.3f spread=%.3f threshold=%.3f (%d reps)",
            low,
            high,
            self.open_palm_ratio,
            self._open_palm.reps,
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
        value = _trimmed_mean(self._swipe_travels) * 0.6
        self.swipe_min_dx = round(_clamp(value, SWIPE_MIN_DX_FLOOR, SWIPE_MIN_DX_CEIL), 3)
        logger.info(
            "Calibration SWIPE: travels=%s swipe_min_dx=%.3f",
            [round(t, 2) for t in self._swipe_travels],
            self.swipe_min_dx,
        )
        self._advance(_PHASE_CORNERS)

    def _observe_corners(self, tip: tuple[float, float]) -> None:
        self._corner_pts.append(tip)
        if len(self._corner_pts) < CORNER_CALIBRATION_SAMPLES:
            return
        xs = [p[0] for p in self._corner_pts]
        ys = [p[1] for p in self._corner_pts]
        x0, x1 = min(xs) + CORNER_ZONE_PAD, max(xs) - CORNER_ZONE_PAD
        y0, y1 = min(ys) + CORNER_ZONE_PAD, max(ys) - CORNER_ZONE_PAD
        if x1 - x0 >= CORNER_ZONE_MIN_SPAN and y1 - y0 >= CORNER_ZONE_MIN_SPAN:
            self.zone_bounds = (
                round(_clamp(x0, 0.0, 1.0), 3),
                round(_clamp(x1, 0.0, 1.0), 3),
                round(_clamp(y0, 0.0, 1.0), 3),
                round(_clamp(y1, 0.0, 1.0), 3),
            )
            logger.info("Calibration CORNERS: zone_bounds=%s", self.zone_bounds)
        else:
            logger.info(
                "Calibration CORNERS: swept area too small (x %.2f-%.2f y %.2f-%.2f), keeping default zone",
                x0, x1, y0, y1,
            )
        self._advance(_PHASE_DONE)

    def persist(self) -> AppliedCalibration:
        applied = AppliedCalibration(
            pinch_threshold=self.pinch_threshold
            if self.pinch_threshold is not None
            else DEFAULT_PINCH_RATIO,
            deadzone_px=self.deadzone_px if self.deadzone_px is not None else CURSOR_DEADZONE_PX,
            min_cutoff=self.min_cutoff if self.min_cutoff is not None else ONE_EURO_MIN_CUTOFF,
            open_palm_ratio=self.open_palm_ratio
            if self.open_palm_ratio is not None
            else DEFAULT_OPEN_PALM_RATIO,
            swipe_min_dx=self.swipe_min_dx if self.swipe_min_dx is not None else SWIPE_MIN_DX,
            zone_bounds=self.zone_bounds,
        )
        # An aborted (e.g. too-dark) run keeps the current defaults rather
        # than writing garbage that then poisons every later session.
        if self.aborted:
            logger.warning("Calibration aborted (%s) — nothing stored", self.abort_reason)
            return applied
        _set_fact(GESTURE_PINCH_THRESHOLD_KEY, f"{applied.pinch_threshold:.4f}")
        _set_fact(GESTURE_DEADZONE_PX_KEY, str(applied.deadzone_px))
        _set_fact(GESTURE_MIN_CUTOFF_KEY, f"{applied.min_cutoff:.3f}")
        _set_fact(GESTURE_OPEN_PALM_RATIO_KEY, f"{applied.open_palm_ratio:.3f}")
        _set_fact(GESTURE_SWIPE_MIN_DX_KEY, f"{applied.swipe_min_dx:.3f}")
        if applied.zone_bounds is not None:
            _set_fact(GESTURE_ZONE_KEY, ",".join(f"{v:.3f}" for v in applied.zone_bounds))
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


def load_min_cutoff() -> float:
    return _load_fact_float(GESTURE_MIN_CUTOFF_KEY, ONE_EURO_MIN_CUTOFF)


def load_open_palm_ratio() -> float:
    return _load_fact_float(GESTURE_OPEN_PALM_RATIO_KEY, DEFAULT_OPEN_PALM_RATIO)


def load_swipe_min_dx() -> float:
    return _load_fact_float(GESTURE_SWIPE_MIN_DX_KEY, SWIPE_MIN_DX)


def load_zone_bounds() -> tuple[float, float, float, float] | None:
    """The personal tracking rectangle (x0, x1, y0, y1) from the corner
    phase, or None if never calibrated (use the symmetric default zone)."""
    stored = profile_service_layer.get_fact(ProfileUnitOfWork(), GESTURE_ZONE_KEY)
    if not stored:
        return None
    try:
        x0, x1, y0, y1 = (float(v) for v in stored.split(","))
    except (ValueError, TypeError):
        return None
    if x1 - x0 < CORNER_ZONE_MIN_SPAN or y1 - y0 < CORNER_ZONE_MIN_SPAN:
        return None
    return (x0, x1, y0, y1)
