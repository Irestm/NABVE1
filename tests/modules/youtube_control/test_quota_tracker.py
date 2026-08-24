from __future__ import annotations

from datetime import date, timedelta

import pytest

from modules.ai_bridge.state_store import StateStore
from modules.youtube_control.quota_tracker import DAILY_UNIT_LIMIT, QuotaTracker


@pytest.fixture
def tracker(tmp_path) -> QuotaTracker:
    return QuotaTracker(store=StateStore(db_path=tmp_path / "state.db"))


def test_units_used_starts_at_zero(tracker: QuotaTracker) -> None:
    assert tracker.units_used() == 0


def test_record_usage_accumulates(tracker: QuotaTracker) -> None:
    tracker.record_usage(100)
    tracker.record_usage(50)

    assert tracker.units_used() == 150


def test_status_reports_remaining_searches(tracker: QuotaTracker) -> None:
    tracker.record_usage(100)

    status = tracker.status()

    assert status.units_used == 100
    assert status.daily_limit == DAILY_UNIT_LIMIT
    assert status.remaining_searches == (DAILY_UNIT_LIMIT - 100) // 100
    assert status.near_limit is False
    assert status.exhausted is False


def test_status_near_limit_at_eighty_percent(tracker: QuotaTracker) -> None:
    tracker.record_usage(int(DAILY_UNIT_LIMIT * 0.8))

    assert tracker.status().near_limit is True


def test_status_not_near_limit_below_eighty_percent(tracker: QuotaTracker) -> None:
    tracker.record_usage(int(DAILY_UNIT_LIMIT * 0.8) - 100)

    assert tracker.status().near_limit is False


def test_status_exhausted_at_full_limit(tracker: QuotaTracker) -> None:
    tracker.record_usage(DAILY_UNIT_LIMIT)

    assert tracker.status().exhausted is True


def test_usage_resets_on_a_new_day(tmp_path) -> None:
    store = StateStore(db_path=tmp_path / "state.db")
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    store.set("last_reset_date", yesterday)
    store.set("units_used", "9999")

    tracker = QuotaTracker(store=store)

    assert tracker.units_used() == 0


def test_consume_near_limit_warning_fires_once(tracker: QuotaTracker) -> None:
    tracker.record_usage(int(DAILY_UNIT_LIMIT * 0.8))

    assert tracker.consume_near_limit_warning() is True
    assert tracker.consume_near_limit_warning() is False


def test_consume_near_limit_warning_false_when_not_near_limit(tracker: QuotaTracker) -> None:
    assert tracker.consume_near_limit_warning() is False
