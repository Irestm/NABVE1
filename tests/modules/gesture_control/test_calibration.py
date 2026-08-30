from __future__ import annotations

import pytest

from modules.gesture_control import calibration
from modules.gesture_control.calibration import CalibrationFrame
from modules.gesture_control.config import (
    CORNER_CALIBRATION_SAMPLES,
    CURSOR_DEADZONE_PX,
    DEFAULT_OPEN_PALM_RATIO,
    DEFAULT_FIST_RATIO,
    ONE_EURO_MIN_CUTOFF,
    STEADY_CALIBRATION_SAMPLES,
    SWIPE_MIN_DX,
)

_REPS = calibration._REQUIRED_REPS  # 5


def _frame(fist=1.6, palm=1.0, tip=(0.5, 0.5), centre=(0.5, 0.5), brightness=120.0) -> CalibrationFrame:
    return CalibrationFrame(
        fist_score=fist, open_palm_score=palm, raw_tip=tip, palm_centre=centre, brightness=brightness
    )


def _do_steady(session: calibration.CalibrationSession, jitter: float = 0.002) -> None:
    for i in range(STEADY_CALIBRATION_SAMPLES):
        offset = jitter if i % 2 == 0 else -jitter
        session.observe(_frame(tip=(0.5 + offset, 0.5)))


def _do_fist(session: calibration.CalibrationSession) -> None:
    for _ in range(_REPS + 1):
        session.observe(_frame(fist=2.0))  # open hand
        session.observe(_frame(fist=0.6))  # closed fist


def _do_open_palm(session: calibration.CalibrationSession) -> None:
    for _ in range(_REPS + 1):
        session.observe(_frame(palm=1.0))  # fist
        session.observe(_frame(palm=1.5))  # spread


def _do_swipe(session: calibration.CalibrationSession) -> None:
    xs: list[float] = []
    for _ in range(_REPS + 2):
        xs += [0.2, 0.35, 0.5, 0.65, 0.5, 0.35, 0.2]
    for x in xs:
        session.observe(_frame(centre=(x, 0.5)))


def _do_corners(session: calibration.CalibrationSession) -> None:
    # sweep the fingertip across a wide rectangle
    for i in range(CORNER_CALIBRATION_SAMPLES):
        x = 0.1 if i % 2 == 0 else 0.9
        y = 0.1 if (i // 2) % 2 == 0 else 0.9
        session.observe(_frame(tip=(x, y)))


def _do_all(session: calibration.CalibrationSession) -> None:
    _do_steady(session)
    _do_fist(session)
    _do_open_palm(session)
    _do_swipe(session)
    _do_corners(session)


def test_phase_order_and_prompts() -> None:
    s = calibration.CalibrationSession(px_per_norm=1000.0)
    assert "неподвижно" in s.take_announcement()
    _do_steady(s)
    assert "сожмите" in s.take_announcement().lower()
    _do_fist(s)
    assert "ладонь" in s.take_announcement().lower()
    _do_open_palm(s)
    assert "влево" in s.take_announcement().lower()
    _do_swipe(s)
    assert "угл" in s.take_announcement().lower()
    _do_corners(s)
    assert "заверш" in s.take_announcement().lower()
    assert s.done is True


def test_progress_reports_phase_and_dots() -> None:
    s = calibration.CalibrationSession(px_per_norm=1000.0)
    p0 = s.progress()
    assert p0.phase_index == 1 and p0.total_phases == 5 and p0.reps_target == _REPS
    assert p0.reps_done == 0 and p0.done is False

    _do_steady(s)
    p1 = s.progress()
    assert p1.phase_index == 2 and "Кулак" in p1.label and p1.reps_done == 0

    # squeeze cycles fill dots one at a time (a rep completes on release)
    for _ in range(3):
        s.observe(_frame(fist=2.0))
        s.observe(_frame(fist=0.6))
        s.observe(_frame(fist=2.0))
    assert 1 <= s.progress().reps_done <= 3

    _do_fist(s)
    _do_open_palm(s)
    _do_swipe(s)
    assert s.progress().phase_index == 5  # corners phase
    _do_corners(s)
    done = s.progress()
    assert done.done is True and done.reps_done == _REPS


def test_dark_input_aborts_and_persists_nothing(monkeypatch) -> None:
    written: dict[str, str] = {}
    monkeypatch.setattr(
        calibration.profile_service_layer,
        "set_fact",
        lambda uow, key, value, **kw: written.__setitem__(key, value),
    )
    s = calibration.CalibrationSession(px_per_norm=1000.0)
    s.take_announcement()  # drain the opening prompt
    for i in range(STEADY_CALIBRATION_SAMPLES):
        off = 0.002 if i % 2 == 0 else -0.002
        s.observe(_frame(tip=(0.5 + off, 0.5), brightness=10.0))  # near-black frames
    assert s.aborted is True and s.done is True
    assert "темно" in s.abort_reason
    assert "отменена" in (s.take_announcement() or "")
    s.persist()
    assert written == {}


def test_steady_phase_sets_deadzone_and_min_cutoff() -> None:
    s = calibration.CalibrationSession(px_per_norm=1000.0)
    _do_steady(s, jitter=0.002)
    assert s.deadzone_px is not None and s.deadzone_px >= 2
    assert s.min_cutoff is not None


def test_fist_phase_threshold_between_closed_and_open() -> None:
    s = calibration.CalibrationSession(px_per_norm=1000.0)
    _do_steady(s)
    _do_fist(s)
    assert s.fist_threshold is not None
    assert 0.7 < s.fist_threshold < 1.5


def test_open_palm_phase_threshold_between_fist_and_spread() -> None:
    s = calibration.CalibrationSession(px_per_norm=1000.0)
    _do_steady(s)
    _do_fist(s)
    _do_open_palm(s)
    assert s.open_palm_ratio is not None
    assert 1.0 < s.open_palm_ratio < 1.5


def test_swipe_phase_learns_a_travel_below_the_users_swing() -> None:
    s = calibration.CalibrationSession(px_per_norm=1000.0)
    _do_steady(s)
    _do_fist(s)
    _do_open_palm(s)
    _do_swipe(s)
    assert s.swipe_min_dx is not None
    assert 0.10 <= s.swipe_min_dx < 0.45


def test_corners_phase_learns_a_zone_rectangle() -> None:
    s = calibration.CalibrationSession(px_per_norm=1000.0)
    _do_all(s)
    assert s.zone_bounds is not None
    x0, x1, y0, y1 = s.zone_bounds
    assert 0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0
    assert x1 - x0 > 0.5 and y1 - y0 > 0.5  # the wide sweep


def test_persist_writes_all_facts_including_zone(monkeypatch) -> None:
    written: dict[str, str] = {}
    monkeypatch.setattr(
        calibration.profile_service_layer,
        "set_fact",
        lambda uow, key, value, **kw: written.__setitem__(key, value),
    )
    s = calibration.CalibrationSession(px_per_norm=1000.0)
    _do_all(s)
    applied = s.persist()

    assert set(written) == {
        "gesture_fist_threshold",
        "gesture_deadzone_px",
        "gesture_min_cutoff",
        "gesture_open_palm_ratio",
        "gesture_swipe_min_dx",
        "gesture_zone_bounds",
    }
    assert abs(float(written["gesture_fist_threshold"]) - applied.fist_threshold) < 1e-4
    assert applied.zone_bounds is not None


def test_persist_falls_back_to_defaults_when_unfinished(monkeypatch) -> None:
    monkeypatch.setattr(calibration.profile_service_layer, "set_fact", lambda *a, **k: None)
    s = calibration.CalibrationSession(px_per_norm=1000.0)
    applied = s.persist()
    assert applied.fist_threshold == DEFAULT_FIST_RATIO
    assert applied.deadzone_px == CURSOR_DEADZONE_PX
    assert applied.min_cutoff == ONE_EURO_MIN_CUTOFF
    assert applied.open_palm_ratio == DEFAULT_OPEN_PALM_RATIO
    assert applied.swipe_min_dx == SWIPE_MIN_DX
    assert applied.zone_bounds is None


def test_loaders_fall_back_to_defaults(monkeypatch) -> None:
    monkeypatch.setattr(calibration.profile_service_layer, "get_fact", lambda uow, key: None)
    assert calibration.load_fist_threshold() == DEFAULT_FIST_RATIO
    assert calibration.load_deadzone_px() == CURSOR_DEADZONE_PX
    assert calibration.load_min_cutoff() == ONE_EURO_MIN_CUTOFF
    assert calibration.load_open_palm_ratio() == DEFAULT_OPEN_PALM_RATIO
    assert calibration.load_swipe_min_dx() == SWIPE_MIN_DX
    assert calibration.load_zone_bounds() is None


@pytest.mark.parametrize(
    "stored, expected",
    [
        ("0.150,0.900,0.300,0.750", (0.15, 0.9, 0.3, 0.75)),
        ("0.4,0.5,0.4,0.5", None),  # span below CORNER_ZONE_MIN_SPAN
        ("garbage", None),
        (None, None),
    ],
)
def test_load_zone_bounds_parses_and_guards(monkeypatch, stored, expected) -> None:
    monkeypatch.setattr(calibration.profile_service_layer, "get_fact", lambda uow, key: stored)
    assert calibration.load_zone_bounds() == expected


def test_loaders_read_stored_values(monkeypatch) -> None:
    stored = {
        "gesture_fist_threshold": "0.41",
        "gesture_deadzone_px": "12",
        "gesture_min_cutoff": "0.9",
        "gesture_open_palm_ratio": "1.28",
        "gesture_swipe_min_dx": "0.19",
    }
    monkeypatch.setattr(
        calibration.profile_service_layer, "get_fact", lambda uow, key: stored.get(key)
    )
    assert calibration.load_fist_threshold() == pytest.approx(0.41)
    assert calibration.load_deadzone_px() == 12
    assert calibration.load_min_cutoff() == pytest.approx(0.9)
    assert calibration.load_open_palm_ratio() == pytest.approx(1.28)
    assert calibration.load_swipe_min_dx() == pytest.approx(0.19)
