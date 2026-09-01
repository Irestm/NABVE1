from __future__ import annotations

import math
from dataclasses import dataclass, field

from core.logger import get_logger
from modules.gesture_control.config import (
    CALIBRATION_MAX_DARK_FRACTION,
    CALIBRATION_MIN_BRIGHTNESS,
    CALIBRATION_PHASE_MAX_FRAMES,
    CORNER_CALIBRATION_SAMPLES,
    CORNER_ZONE_MIN_SPAN,
    CORNER_ZONE_MIN_WIDTH,
    CORNER_ZONE_PAD,
    CURSOR_DEADZONE_PX,
    DEADZONE_PX_MAX,
    DEADZONE_PX_MIN,
    FIST_CLICK_ENG_MAX,
    FIST_CLICK_ENG_MIN,
    FIST_CLICK_ENGAGE,
    FIST_CLICK_REL_MAX,
    FIST_CLICK_RELEASE,
    JITTER_HIGH_PX,
    JITTER_LOW_PX,
    MIN_CUTOFF_CEIL,
    MIN_CUTOFF_FLOOR,
    ONE_EURO_MIN_CUTOFF,
    STEADY_CALIBRATION_SAMPLES,
)

logger = get_logger(__name__)

_REQUIRED_REPS = 5   # STEADY/CORNERS "dot" scaling
_CLICK_REPS = 3      # balls to fist-pop in the CLICK stage (red / blue / yellow)

_PHASE_STEADY = "steady"
_PHASE_CORNERS = "corners"
_PHASE_CLICK = "click"
_PHASE_DONE = "done"

_TOTAL_PHASES = 3

# Only the first and last prompts are spoken (see _advance); the middle
# phases pass None so the voice stays quiet — the on-screen game leads.
_PROMPTS = {
    _PHASE_STEADY: "Обучение. Следуйте подсказкам на экране.",
    _PHASE_CORNERS: None,
    _PHASE_CLICK: None,
    _PHASE_DONE: None,   # the game speaks the "молодец" line when IT finishes
}

_PHASE_META = {
    _PHASE_STEADY: (1, "Наведись и замри", "Указательный на шарик в центре, держи руку спокойно"),
    _PHASE_CORNERS: (2, "Шарики по краям", "Наведись указательным на каждый шарик у края экрана"),
    _PHASE_CLICK: (3, "Лопни кулаком", "Наведись на шарик и сожми кулак — по очереди на каждый"),
}


@dataclass(frozen=True)
class CalibrationFrame:
    tip: tuple[float, float]     # the index fingertip (what the cursor follows), normalised
    index_middle_gap: float      # index-tip to middle-tip distance / hand size (diag only now)
    pointing: bool               # is the hand in the two-finger pointing pose?
    brightness: float = -1.0
    fist: float = 1.0            # median finger straightness: low = fist (drives the CLICK phase)


@dataclass(frozen=True)
class CalibrationProgress:
    phase_index: int
    total_phases: int
    label: str
    instruction: str
    reps_done: int
    reps_target: int
    done: bool
    phase_key: str = _PHASE_STEADY   # "steady"|"corners"|"click"|"done" — game screen selector


@dataclass(frozen=True)
class AppliedCalibration:
    min_cutoff: float
    deadzone_px: int
    zone_bounds: tuple[float, float, float, float] | None
    click_gap_engage: float
    click_gap_release: float


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _widen(lo: float, hi: float, min_width: float) -> tuple[float, float]:
    """Grow [lo, hi] symmetrically around its centre to at least min_width."""
    if hi - lo >= min_width:
        return lo, hi
    c = (lo + hi) / 2
    return c - min_width / 2, c + min_width / 2


def _lerp_min_cutoff(jitter_px: float) -> float:
    span = max(JITTER_HIGH_PX - JITTER_LOW_PX, 1e-6)
    t = _clamp((jitter_px - JITTER_LOW_PX) / span, 0.0, 1.0)
    return round(MIN_CUTOFF_CEIL + (MIN_CUTOFF_FLOOR - MIN_CUTOFF_CEIL) * t, 3)


def _trimmed_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) >= 3:
        ordered = ordered[1:-1]
    return sum(ordered) / len(ordered)


class _RepCounter:
    """Counts "do it N times" for a scalar that dips LOW during the gesture
    and rises between reps (both the pinch-gap and the fist do this).
    Records the extreme reached on each side."""

    def __init__(self, min_span: float) -> None:
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
        if span < self._min_span:
            return
        band = span * 0.15
        mid = (low + high) / 2
        enter, leave = value <= mid - band, value >= mid + band

        if self._cur_extreme is None:
            self._cur_extreme = value
        elif self._in_gesture:
            self._cur_extreme = min(self._cur_extreme, value)
        else:
            self._cur_extreme = max(self._cur_extreme, value)

        if not self._in_gesture and enter:
            self._rest_extremes.append(self._cur_extreme)
            self._in_gesture = True
            self._cur_extreme = value
        elif self._in_gesture and leave:
            self._gesture_extremes.append(self._cur_extreme)
            self._in_gesture = False
            self._cur_extreme = value
            self.reps += 1

    def closed_level(self) -> float:
        return _trimmed_mean(self._gesture_extremes)

    def open_level(self) -> float:
        if self._rest_extremes:
            return _trimmed_mean(self._rest_extremes)
        return max(self._samples) if self._samples else 0.0


@dataclass
class CalibrationSession:
    """The wizard for the absolute + finger-state model: STEADY (fingertip
    tremor -> smoothing + deadzone) -> CORNERS (four screen corners -> the
    absolute mapping rectangle) -> CLICK (index/middle tips together ->
    click thresholds). Every output is applied by the worker."""

    px_per_norm: float = 3000.0   # screen px per 1.0 of normalised frame travel

    _phase: str = _PHASE_STEADY
    _pending: str | None = _PROMPTS[_PHASE_STEADY]

    _steady_pts: list[tuple[float, float]] = field(default_factory=list)
    _corner_pts: list[tuple[float, float]] = field(default_factory=list)
    _click: _RepCounter = field(default_factory=lambda: _RepCounter(min_span=0.10))

    done: bool = False
    aborted: bool = False
    abort_reason: str = ""
    _dark_frames: int = 0
    _total_frames: int = 0
    _frames_in_phase: int = 0

    min_cutoff: float | None = None
    deadzone_px: int | None = None
    zone_bounds: tuple[float, float, float, float] | None = None
    click_gap_engage: float | None = None
    click_gap_release: float | None = None

    def take_announcement(self) -> str | None:
        message, self._pending = self._pending, None
        return message

    def progress(self) -> CalibrationProgress:
        if self._phase == _PHASE_DONE:
            return CalibrationProgress(
                _TOTAL_PHASES, _TOTAL_PHASES, "Готово", "Обучение пройдено",
                _CLICK_REPS, _CLICK_REPS, True, _PHASE_DONE,
            )
        index, label, instruction = _PHASE_META[self._phase]
        if self._phase == _PHASE_STEADY:
            done = len(self._steady_pts) * _CLICK_REPS // max(STEADY_CALIBRATION_SAMPLES, 1)
        elif self._phase == _PHASE_CORNERS:
            done = len(self._corner_pts) * _CLICK_REPS // max(CORNER_CALIBRATION_SAMPLES, 1)
        else:
            done = self._click.reps
        return CalibrationProgress(
            index, _TOTAL_PHASES, label, instruction,
            min(_CLICK_REPS, done), _CLICK_REPS, False, self._phase,
        )

    def _advance(self, phase: str) -> None:
        self._frames_in_phase = 0
        if (
            phase != _PHASE_DONE
            and not self.aborted
            and self._total_frames >= 30
            and self._dark_frames / self._total_frames > CALIBRATION_MAX_DARK_FRACTION
        ):
            self._abort("слишком темно, добавьте света и повторите")
            return
        self._phase = phase
        self._pending = _PROMPTS[phase]
        if phase == _PHASE_DONE:
            self.done = True

    def observe(self, frame: CalibrationFrame) -> None:
        if self.done:
            return
        self._total_frames += 1
        self._frames_in_phase += 1
        if 0 <= frame.brightness < CALIBRATION_MIN_BRIGHTNESS:
            self._dark_frames += 1
        if self._phase == _PHASE_STEADY:
            if frame.pointing:
                self._steady_pts.append(frame.tip)
                if len(self._steady_pts) >= STEADY_CALIBRATION_SAMPLES:
                    self._finalize_steady()
        elif self._phase == _PHASE_CORNERS:
            if frame.pointing:
                self._corner_pts.append(frame.tip)
                if len(self._corner_pts) >= CORNER_CALIBRATION_SAMPLES:
                    self._finalize_corners()
        elif self._phase == _PHASE_CLICK:
            # A fist is not the "pointing" pose, so observe every hand frame
            # here; `_RepCounter` (active-low) counts the curl/open reps off
            # the median-straightness signal.
            self._click.observe(frame.fist)
            if self._click.reps >= _CLICK_REPS:
                self._finish_click()
        if not self.done and self._frames_in_phase > CALIBRATION_PHASE_MAX_FRAMES:
            self._force_finish_phase()

    def _force_finish_phase(self) -> None:
        logger.warning(
            "Calibration %s: no result after %d frames — using the default and moving on",
            self._phase, self._frames_in_phase,
        )
        if self._phase == _PHASE_STEADY:
            self._finalize_steady()
        elif self._phase == _PHASE_CORNERS:
            self._finalize_corners()
        elif self._phase == _PHASE_CLICK:
            self._finish_click()

    def _abort(self, reason: str) -> None:
        self.aborted = True
        self.abort_reason = reason
        self._pending = f"Обучение прервано: {reason}."
        self._phase = _PHASE_DONE
        self.done = True

    def _finalize_steady(self) -> None:
        if self._total_frames and self._dark_frames / self._total_frames > CALIBRATION_MAX_DARK_FRACTION:
            self._abort("слишком темно, добавьте света и повторите")
            return
        pts = self._steady_pts
        if len(pts) < 10:
            logger.info("Calibration STEADY: too few samples, keeping defaults")
            self._advance(_PHASE_CORNERS)
            return
        n = len(pts)
        mx = sum(p[0] for p in pts) / n
        my = sum(p[1] for p in pts) / n
        rms = math.sqrt(sum((p[0] - mx) ** 2 + (p[1] - my) ** 2 for p in pts) / n)
        jitter_px = rms * self.px_per_norm
        self.deadzone_px = int(_clamp(round(jitter_px * 2 + 2), DEADZONE_PX_MIN, DEADZONE_PX_MAX))
        self.min_cutoff = _lerp_min_cutoff(jitter_px)
        logger.info(
            "Calibration STEADY: tremor=%.1fpx -> deadzone=%dpx min_cutoff=%.2f",
            jitter_px, self.deadzone_px, self.min_cutoff,
        )
        self._advance(_PHASE_CORNERS)

    def _finalize_corners(self) -> None:
        pts = self._corner_pts
        if len(pts) < 8:
            logger.info("Calibration CORNERS: too few samples, keeping the default zone")
            self._advance(_PHASE_CLICK)
            return
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x0, x1 = min(xs) + CORNER_ZONE_PAD, max(xs) - CORNER_ZONE_PAD
        y0, y1 = min(ys) + CORNER_ZONE_PAD, max(ys) - CORNER_ZONE_PAD
        if x1 - x0 >= CORNER_ZONE_MIN_SPAN and y1 - y0 >= CORNER_ZONE_MIN_SPAN:
            # A too-narrow (but non-trivial) sweep would give a huge mapping
            # gain -> hypersensitive cursor. Expand each axis around its
            # centre to at least CORNER_ZONE_MIN_WIDTH.
            x0, x1 = _widen(x0, x1, CORNER_ZONE_MIN_WIDTH)
            y0, y1 = _widen(y0, y1, CORNER_ZONE_MIN_WIDTH)
            self.zone_bounds = (
                round(_clamp(x0, 0.0, 1.0), 3),
                round(_clamp(x1, 0.0, 1.0), 3),
                round(_clamp(y0, 0.0, 1.0), 3),
                round(_clamp(y1, 0.0, 1.0), 3),
            )
            logger.info("Calibration CORNERS: zone_bounds=%s", self.zone_bounds)
        else:
            logger.info(
                "Calibration CORNERS: swept area too small (x %.2f-%.2f y %.2f-%.2f), keeping default",
                x0, x1, y0, y1,
            )
        self._advance(_PHASE_CLICK)

    def _finish_click(self) -> None:
        closed = self._click.closed_level()   # deepest fist (straightness low)
        open_ = self._click.open_level()      # hand open (straightness high)
        span = open_ - closed
        if self._click.reps < 2 or span < 0.08:
            self.click_gap_engage = FIST_CLICK_ENGAGE
            self.click_gap_release = FIST_CLICK_RELEASE
            logger.info(
                "Calibration CLICK: weak data (reps=%d span=%.3f) — defaults %.2f/%.2f",
                self._click.reps, span, self.click_gap_engage, self.click_gap_release,
            )
        else:
            eng = _clamp(closed + span * 0.30, FIST_CLICK_ENG_MIN, FIST_CLICK_ENG_MAX)
            rel = _clamp(closed + span * 0.60, eng + 0.06, FIST_CLICK_REL_MAX)
            self.click_gap_engage = round(eng, 3)
            self.click_gap_release = round(rel, 3)
            logger.info(
                "Calibration CLICK: fist=%.3f open=%.3f -> engage=%.3f release=%.3f (%d reps)",
                closed, open_, self.click_gap_engage, self.click_gap_release, self._click.reps,
            )
        self._advance(_PHASE_DONE)

    def persist(self) -> AppliedCalibration:
        # "Обучение" is a pure tutorial now — it measures and stores NOTHING.
        # Control always runs on the built-in defaults.
        return AppliedCalibration(
            min_cutoff=ONE_EURO_MIN_CUTOFF,
            deadzone_px=CURSOR_DEADZONE_PX,
            zone_bounds=None,
            click_gap_engage=FIST_CLICK_ENGAGE,
            click_gap_release=FIST_CLICK_RELEASE,
        )


# The loaders return the fixed defaults — there is no per-user calibration.
def load_min_cutoff() -> float:
    return ONE_EURO_MIN_CUTOFF


def load_deadzone_px() -> int:
    return CURSOR_DEADZONE_PX


def load_click_gap_thresholds() -> tuple[float, float]:
    return FIST_CLICK_ENGAGE, FIST_CLICK_RELEASE


def load_zone_bounds() -> tuple[float, float, float, float] | None:
    return None
