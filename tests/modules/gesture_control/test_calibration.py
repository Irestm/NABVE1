from __future__ import annotations

import pytest

from modules.gesture_control import calibration
from modules.gesture_control.calibration import CalibrationFrame
from modules.gesture_control.config import (
    CURSOR_DEADZONE_PX,
    DEFAULT_OPEN_PALM_RATIO,
    DEFAULT_PINCH_RATIO,
    EMA_MIN_ALPHA,
    STEADY_CALIBRATION_SAMPLES,
    SWIPE_MIN_DX,
)


def _frame(pinch=1.0, palm=1.0, tip=(0.5, 0.5), centre=(0.5, 0.5)) -> CalibrationFrame:
    return CalibrationFrame(pinch_ratio=pinch, open_palm_score=palm, raw_tip=tip, palm_centre=centre)


def _do_steady(session: calibration.CalibrationSession, jitter: float = 0.002) -> None:
    for i in range(STEADY_CALIBRATION_SAMPLES):
        offset = jitter if i % 2 == 0 else -jitter
        session.observe(_frame(tip=(0.5 + offset, 0.5)))


def _do_pinch(session: calibration.CalibrationSession, reps: int = 3) -> None:
    for _ in range(reps + 1):
        session.observe(_frame(pinch=1.2))  # open
        session.observe(_frame(pinch=0.30))  # squeezed


def _do_open_palm(session: calibration.CalibrationSession, reps: int = 3) -> None:
    for _ in range(reps + 1):
        session.observe(_frame(palm=1.0))  # fist
        session.observe(_frame(palm=1.5))  # spread


def _do_swipe(session: calibration.CalibrationSession, cycles: int = 4) -> None:
    xs: list[float] = []
    for _ in range(cycles):
        xs += [0.2, 0.35, 0.5, 0.65, 0.5, 0.35, 0.2]
    for x in xs:
        session.observe(_frame(centre=(x, 0.5)))


def test_phase_order_and_prompts() -> None:
    s = calibration.CalibrationSession(px_per_norm=1000.0)
    assert "неподвижно" in s.take_announcement()
    _do_steady(s)
    assert "сожмите" in s.take_announcement().lower()
    _do_pinch(s)
    assert "ладонь" in s.take_announcement().lower()
    _do_open_palm(s)
    assert "влево" in s.take_announcement().lower()
    _do_swipe(s)
    assert "заверш" in s.take_announcement().lower()
    assert s.done is True


def test_steady_phase_sets_deadzone_and_min_alpha() -> None:
    s = calibration.CalibrationSession(px_per_norm=1000.0)
    _do_steady(s, jitter=0.002)
    assert s.deadzone_px is not None and s.deadzone_px >= 2
    assert s.min_alpha is not None


def test_pinch_phase_threshold_between_squeezed_and_open() -> None:
    s = calibration.CalibrationSession(px_per_norm=1000.0)
    _do_steady(s)
    _do_pinch(s)
    assert s.pinch_threshold is not None
    assert 0.30 < s.pinch_threshold < 1.2


def test_open_palm_phase_threshold_between_fist_and_spread() -> None:
    s = calibration.CalibrationSession(px_per_norm=1000.0)
    _do_steady(s)
    _do_pinch(s)
    _do_open_palm(s)
    assert s.open_palm_ratio is not None
    assert 1.0 < s.open_palm_ratio < 1.5


def test_swipe_phase_learns_a_travel_below_the_users_swing() -> None:
    s = calibration.CalibrationSession(px_per_norm=1000.0)
    _do_steady(s)
    _do_pinch(s)
    _do_open_palm(s)
    _do_swipe(s)
    assert s.swipe_min_dx is not None
    # user's swing was ~0.45; the learned trigger is a fraction of it
    assert 0.10 <= s.swipe_min_dx < 0.45


def test_persist_writes_all_five_facts(monkeypatch) -> None:
    written: dict[str, str] = {}
    monkeypatch.setattr(
        calibration.profile_service_layer,
        "set_fact",
        lambda uow, key, value, **kw: written.__setitem__(key, value),
    )
    s = calibration.CalibrationSession(px_per_norm=1000.0)
    _do_steady(s)
    _do_pinch(s)
    _do_open_palm(s)
    _do_swipe(s)
    applied = s.persist()

    assert set(written) == {
        "gesture_pinch_threshold",
        "gesture_deadzone_px",
        "gesture_min_alpha",
        "gesture_open_palm_ratio",
        "gesture_swipe_min_dx",
    }
    assert abs(float(written["gesture_pinch_threshold"]) - applied.pinch_threshold) < 1e-4
    assert float(written["gesture_open_palm_ratio"]) == applied.open_palm_ratio


def test_persist_falls_back_to_defaults_when_unfinished(monkeypatch) -> None:
    monkeypatch.setattr(calibration.profile_service_layer, "set_fact", lambda *a, **k: None)
    s = calibration.CalibrationSession(px_per_norm=1000.0)
    applied = s.persist()
    assert applied.pinch_threshold == DEFAULT_PINCH_RATIO
    assert applied.deadzone_px == CURSOR_DEADZONE_PX
    assert applied.min_alpha == EMA_MIN_ALPHA
    assert applied.open_palm_ratio == DEFAULT_OPEN_PALM_RATIO
    assert applied.swipe_min_dx == SWIPE_MIN_DX


def test_loaders_fall_back_to_defaults(monkeypatch) -> None:
    monkeypatch.setattr(calibration.profile_service_layer, "get_fact", lambda uow, key: None)
    assert calibration.load_threshold() == DEFAULT_PINCH_RATIO
    assert calibration.load_deadzone_px() == CURSOR_DEADZONE_PX
    assert calibration.load_min_alpha() == EMA_MIN_ALPHA
    assert calibration.load_open_palm_ratio() == DEFAULT_OPEN_PALM_RATIO
    assert calibration.load_swipe_min_dx() == SWIPE_MIN_DX


def test_loaders_read_stored_values(monkeypatch) -> None:
    stored = {
        "gesture_pinch_threshold": "0.41",
        "gesture_deadzone_px": "12",
        "gesture_min_alpha": "0.05",
        "gesture_open_palm_ratio": "1.28",
        "gesture_swipe_min_dx": "0.19",
    }
    monkeypatch.setattr(
        calibration.profile_service_layer, "get_fact", lambda uow, key: stored.get(key)
    )
    assert calibration.load_threshold() == pytest.approx(0.41)
    assert calibration.load_deadzone_px() == 12
    assert calibration.load_min_alpha() == pytest.approx(0.05)
    assert calibration.load_open_palm_ratio() == pytest.approx(1.28)
    assert calibration.load_swipe_min_dx() == pytest.approx(0.19)
