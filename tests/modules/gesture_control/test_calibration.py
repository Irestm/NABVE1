from __future__ import annotations

import pytest

from modules.gesture_control import calibration
from modules.gesture_control.config import (
    CURSOR_DEADZONE_PX,
    DEFAULT_PINCH_RATIO,
    EMA_MIN_ALPHA,
    MIN_ALPHA_CEIL,
    MIN_ALPHA_FLOOR,
    STEADY_CALIBRATION_SAMPLES,
)


def _feed_steady(session: calibration.CalibrationSession, jitter: float) -> None:
    # Alternating ±jitter about a fixed centre -> RMS deviation ~= jitter.
    for i in range(STEADY_CALIBRATION_SAMPLES):
        offset = jitter if i % 2 == 0 else -jitter
        session.observe(1.0, (0.5 + offset, 0.5))


def _run_pinch_cycles(session: calibration.CalibrationSession, cycles: int) -> None:
    for _ in range(cycles):
        for value in (0.12, 0.08, 0.02, 0.02, 0.08, 0.12):
            session.observe(value, (0.5, 0.5))


def test_steady_phase_derives_a_small_deadzone_for_a_steady_hand() -> None:
    session = calibration.CalibrationSession(px_per_norm=1000.0)
    _feed_steady(session, jitter=0.0015)  # ~1.5 px of tremor
    assert session.deadzone_px is not None
    assert CURSOR_DEADZONE_PX <= session.deadzone_px <= 10
    assert session.min_alpha == pytest.approx(MIN_ALPHA_CEIL, abs=0.02)


def test_steady_phase_derives_a_bigger_deadzone_and_heavier_smoothing_for_a_shaky_hand() -> None:
    steady = calibration.CalibrationSession(px_per_norm=1000.0)
    _feed_steady(steady, jitter=0.0015)
    shaky = calibration.CalibrationSession(px_per_norm=1000.0)
    _feed_steady(shaky, jitter=0.010)  # ~10 px of tremor

    assert shaky.deadzone_px > steady.deadzone_px
    assert shaky.min_alpha == pytest.approx(MIN_ALPHA_FLOOR, abs=0.01)


def test_full_flow_completes_only_after_steady_then_three_pinch_cycles() -> None:
    session = calibration.CalibrationSession(px_per_norm=1000.0)
    _feed_steady(session, jitter=0.002)
    assert session.done is False
    _run_pinch_cycles(session, 1)
    assert session.done is False
    _run_pinch_cycles(session, 2)
    assert session.done is True
    assert session.threshold is not None
    assert 0.02 < session.threshold < 0.12


def test_announcement_sequence() -> None:
    session = calibration.CalibrationSession(px_per_norm=1000.0)
    first = session.take_announcement()
    assert first is not None and "неподвижно" in first
    assert session.take_announcement() is None

    _feed_steady(session, jitter=0.002)
    second = session.take_announcement()
    assert second is not None and "сожмите" in second.lower()

    _run_pinch_cycles(session, 3)
    third = session.take_announcement()
    assert third is not None and "заверш" in third.lower()


def test_persist_writes_all_three_profile_facts(monkeypatch) -> None:
    written: dict[str, str] = {}
    monkeypatch.setattr(
        calibration.profile_service_layer,
        "set_fact",
        lambda uow, key, value, **kw: written.__setitem__(key, value),
    )
    session = calibration.CalibrationSession(px_per_norm=1000.0)
    _feed_steady(session, jitter=0.003)
    _run_pinch_cycles(session, 3)

    threshold, deadzone, min_alpha = session.persist()

    assert abs(float(written["gesture_pinch_threshold"]) - threshold) < 1e-4
    assert int(written["gesture_deadzone_px"]) == deadzone
    assert abs(float(written["gesture_min_alpha"]) - min_alpha) < 1e-3


def test_load_helpers_fall_back_to_defaults(monkeypatch) -> None:
    monkeypatch.setattr(calibration.profile_service_layer, "get_fact", lambda uow, key: None)
    assert calibration.load_threshold() == DEFAULT_PINCH_RATIO
    assert calibration.load_deadzone_px() == CURSOR_DEADZONE_PX
    assert calibration.load_min_alpha() == EMA_MIN_ALPHA


def test_load_helpers_read_stored_values(monkeypatch) -> None:
    stored = {
        "gesture_pinch_threshold": "0.041",
        "gesture_deadzone_px": "12",
        "gesture_min_alpha": "0.05",
    }
    monkeypatch.setattr(
        calibration.profile_service_layer, "get_fact", lambda uow, key: stored.get(key)
    )
    assert calibration.load_threshold() == pytest.approx(0.041)
    assert calibration.load_deadzone_px() == 12
    assert calibration.load_min_alpha() == pytest.approx(0.05)
