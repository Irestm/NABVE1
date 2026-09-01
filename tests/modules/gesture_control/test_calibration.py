from __future__ import annotations

import pytest

from modules.gesture_control import calibration
from modules.gesture_control.calibration import CalibrationFrame
from modules.gesture_control.config import (
    CALIBRATION_PHASE_MAX_FRAMES,
    CORNER_CALIBRATION_SAMPLES,
    CURSOR_DEADZONE_PX,
    FIST_CLICK_ENGAGE,
    FIST_CLICK_RELEASE,
    ONE_EURO_MIN_CUTOFF,
    STEADY_CALIBRATION_SAMPLES,
)

_REPS = calibration._REQUIRED_REPS  # 5


def _frame(
    tip=(0.5, 0.5), gap=0.5, pointing=True, brightness=120.0, fist=1.0
) -> CalibrationFrame:
    return CalibrationFrame(
        tip=tip, index_middle_gap=gap, pointing=pointing, brightness=brightness, fist=fist
    )


def _do_steady(session, jitter: float = 0.001) -> None:
    for i in range(STEADY_CALIBRATION_SAMPLES):
        off = jitter if i % 2 == 0 else -jitter
        session.observe(_frame(tip=(0.5 + off, 0.5)))


def _do_corners(session) -> None:
    for i in range(CORNER_CALIBRATION_SAMPLES):
        x = 0.15 if i % 2 == 0 else 0.85
        y = 0.15 if (i // 2) % 2 == 0 else 0.85
        session.observe(_frame(tip=(x, y)))


def _do_click(session) -> None:
    for _ in range(_REPS + 1):
        session.observe(_frame(fist=0.95))  # hand open
        session.observe(_frame(fist=0.30))  # fist closed


def _do_all(session) -> None:
    _do_steady(session)
    _do_corners(session)
    _do_click(session)


def test_phase_order_and_prompts() -> None:
    s = calibration.CalibrationSession(px_per_norm=3000.0)
    assert s._phase == calibration._PHASE_STEADY
    assert "подсказк" in (s.take_announcement() or "").lower()
    assert s.progress().phase_key == "steady"
    _do_steady(s)
    assert s._phase == calibration._PHASE_CORNERS
    assert s.progress().phase_key == "corners"
    _do_corners(s)
    assert s._phase == calibration._PHASE_CLICK
    assert s.progress().phase_key == "click"
    _do_click(s)
    assert s._phase == calibration._PHASE_DONE and s.done is True
    assert s.progress().phase_key == "done"


def test_progress_reports_three_phases() -> None:
    s = calibration.CalibrationSession(px_per_norm=3000.0)
    p = s.progress()
    assert p.phase_index == 1 and p.total_phases == 3 and p.done is False
    _do_steady(s)
    assert s.progress().phase_index == 2


def test_steady_sets_cutoff_and_deadzone() -> None:
    s = calibration.CalibrationSession(px_per_norm=3000.0)
    _do_steady(s, jitter=0.001)
    assert s.min_cutoff is not None
    assert s.deadzone_px is not None and s.deadzone_px >= 2


def test_corners_learns_a_zone_rectangle() -> None:
    s = calibration.CalibrationSession(px_per_norm=3000.0)
    _do_steady(s)
    _do_corners(s)
    assert s.zone_bounds is not None
    x0, x1, y0, y1 = s.zone_bounds
    assert 0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0
    assert x1 - x0 > 0.4 and y1 - y0 > 0.4


def test_click_engage_between_fist_and_open() -> None:
    s = calibration.CalibrationSession(px_per_norm=3000.0)
    _do_all(s)
    assert s.click_gap_engage is not None and s.click_gap_release is not None
    assert 0.30 <= s.click_gap_engage < s.click_gap_release < 0.95


def test_non_pointing_frames_are_ignored_in_steady() -> None:
    s = calibration.CalibrationSession(px_per_norm=3000.0)
    for _ in range(STEADY_CALIBRATION_SAMPLES * 2):
        s.observe(_frame(tip=(0.9, 0.1), pointing=False))
    assert s._phase == calibration._PHASE_STEADY  # nothing counted
    assert len(s._steady_pts) == 0


def test_persist_writes_facts(monkeypatch) -> None:
    written: dict[str, str] = {}
    monkeypatch.setattr(
        calibration.profile_service_layer,
        "set_fact",
        lambda uow, key, value, **kw: written.__setitem__(key, value),
    )
    s = calibration.CalibrationSession(px_per_norm=3000.0)
    _do_all(s)
    s.persist()
    assert set(written) == {
        "gesture_min_cutoff",
        "gesture_deadzone_px",
        "gesture_zone_bounds",
        "gesture_click_gap_engage",
        "gesture_click_gap_release",
    }


def test_persist_falls_back_to_defaults_when_unfinished(monkeypatch) -> None:
    monkeypatch.setattr(calibration.profile_service_layer, "set_fact", lambda *a, **k: None)
    applied = calibration.CalibrationSession().persist()
    assert applied.min_cutoff == ONE_EURO_MIN_CUTOFF
    assert applied.deadzone_px == CURSOR_DEADZONE_PX
    assert applied.zone_bounds is None
    assert applied.click_gap_engage == FIST_CLICK_ENGAGE
    assert applied.click_gap_release == FIST_CLICK_RELEASE


def test_loaders_fall_back_to_defaults(monkeypatch) -> None:
    monkeypatch.setattr(calibration.profile_service_layer, "get_fact", lambda uow, key: None)
    assert calibration.load_min_cutoff() == ONE_EURO_MIN_CUTOFF
    assert calibration.load_deadzone_px() == CURSOR_DEADZONE_PX
    assert calibration.load_click_gap_thresholds() == (FIST_CLICK_ENGAGE, FIST_CLICK_RELEASE)
    assert calibration.load_zone_bounds() is None


def test_loaders_read_stored_values(monkeypatch) -> None:
    stored = {
        "gesture_min_cutoff": "0.7",
        "gesture_deadzone_px": "9",
        "gesture_click_gap_engage": "0.18",
        "gesture_click_gap_release": "0.42",
        "gesture_zone_bounds": "0.10,0.90,0.15,0.80",
    }
    monkeypatch.setattr(
        calibration.profile_service_layer, "get_fact", lambda uow, key: stored.get(key)
    )
    assert calibration.load_min_cutoff() == 0.7
    assert calibration.load_deadzone_px() == 9
    assert calibration.load_click_gap_thresholds() == (0.18, 0.42)
    assert calibration.load_zone_bounds() == (0.10, 0.90, 0.15, 0.80)


@pytest.mark.parametrize(
    "stored, expected",
    [
        ("0.10,0.90,0.15,0.80", (0.10, 0.90, 0.15, 0.80)),
        ("0.4,0.5,0.4,0.5", None),  # span below CORNER_ZONE_MIN_SPAN
        ("garbage", None),
        (None, None),
    ],
)
def test_load_zone_bounds_guards(monkeypatch, stored, expected) -> None:
    monkeypatch.setattr(calibration.profile_service_layer, "get_fact", lambda uow, key: stored)
    assert calibration.load_zone_bounds() == expected


def test_click_phase_times_out_and_uses_defaults() -> None:
    s = calibration.CalibrationSession(px_per_norm=3000.0)
    _do_steady(s)
    _do_corners(s)
    assert s._phase == calibration._PHASE_CLICK
    for _ in range(CALIBRATION_PHASE_MAX_FRAMES + 2):
        s.observe(_frame(gap=0.5))  # flat -> never a rep
    assert s._phase != calibration._PHASE_CLICK
    assert s.click_gap_engage == FIST_CLICK_ENGAGE
    assert s.aborted is False


def test_wizard_completes_even_if_every_phase_times_out() -> None:
    s = calibration.CalibrationSession(px_per_norm=3000.0)
    for _ in range(CALIBRATION_PHASE_MAX_FRAMES * 4):
        s.observe(_frame(tip=(0.5, 0.5), gap=0.5))
    assert s.done is True and s.aborted is False


def test_going_dark_aborts_at_the_next_boundary() -> None:
    s = calibration.CalibrationSession(px_per_norm=3000.0)
    _do_steady(s)
    assert s._phase == calibration._PHASE_CORNERS
    for _ in range(CALIBRATION_PHASE_MAX_FRAMES + 10):
        s.observe(_frame(tip=(0.5, 0.5), brightness=8.0))  # dark + not sweeping -> times out
    assert s.aborted is True and "темно" in s.abort_reason


def test_dark_steady_aborts_and_persists_nothing(monkeypatch) -> None:
    written: dict[str, str] = {}
    monkeypatch.setattr(
        calibration.profile_service_layer,
        "set_fact",
        lambda uow, key, value, **kw: written.__setitem__(key, value),
    )
    s = calibration.CalibrationSession(px_per_norm=3000.0)
    s.take_announcement()
    for i in range(STEADY_CALIBRATION_SAMPLES):
        off = 0.001 if i % 2 == 0 else -0.001
        s.observe(_frame(tip=(0.5 + off, 0.5), brightness=8.0))
    assert s.aborted is True and "темно" in s.abort_reason
    s.persist()
    assert written == {}
