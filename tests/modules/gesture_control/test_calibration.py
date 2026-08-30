from __future__ import annotations

import pytest

from modules.gesture_control import calibration
from modules.gesture_control.config import DEFAULT_PINCH_THRESHOLD


def _run_cycles(session: calibration.CalibrationSession, cycles: int) -> None:
    # Each cycle: open (0.12) -> close (0.02) -> open (0.12).
    for _ in range(cycles):
        for value in (0.12, 0.08, 0.02, 0.02, 0.08, 0.12):
            session.observe(value)


def test_completes_after_three_cycles_and_computes_a_threshold_between_tight_and_wide() -> None:
    session = calibration.CalibrationSession()
    assert session.done is False
    _run_cycles(session, 3)
    assert session.done is True
    assert session.threshold is not None
    assert 0.02 < session.threshold < 0.12


def test_does_not_complete_early() -> None:
    session = calibration.CalibrationSession()
    _run_cycles(session, 1)
    assert session.done is False
    assert session.cycles_done <= 1


def test_persist_writes_the_profile_fact(monkeypatch) -> None:
    written: dict[str, str] = {}
    monkeypatch.setattr(
        calibration.profile_service_layer,
        "set_fact",
        lambda uow, key, value, **kw: written.__setitem__(key, value),
    )
    session = calibration.CalibrationSession()
    _run_cycles(session, 3)

    value = session.persist()

    assert "gesture_pinch_threshold" in written
    assert abs(float(written["gesture_pinch_threshold"]) - value) < 1e-4


def test_load_threshold_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setattr(calibration.profile_service_layer, "get_fact", lambda uow, key: None)
    assert calibration.load_threshold() == DEFAULT_PINCH_THRESHOLD


def test_load_threshold_reads_a_stored_value(monkeypatch) -> None:
    monkeypatch.setattr(calibration.profile_service_layer, "get_fact", lambda uow, key: "0.041")
    assert calibration.load_threshold() == pytest.approx(0.041)
