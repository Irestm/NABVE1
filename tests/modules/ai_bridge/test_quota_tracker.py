from __future__ import annotations

from datetime import date, timedelta

from modules.ai_bridge.quota_tracker import QuotaTracker
from modules.ai_bridge.state_store import StateStore


def test_is_near_limit_false_when_no_requests_recorded() -> None:
    tracker = QuotaTracker()

    assert tracker.is_near_limit("groq_api") is False


def test_is_near_limit_true_after_enough_requests_in_the_window() -> None:
    tracker = QuotaTracker()
    for _ in range(20):
        tracker.record_request("groq_api")

    assert tracker.is_near_limit("groq_api") is True


def test_is_near_limit_false_just_under_the_threshold() -> None:
    tracker = QuotaTracker()
    for _ in range(19):
        tracker.record_request("groq_api")

    assert tracker.is_near_limit("groq_api") is False


def test_providers_are_tracked_independently() -> None:
    tracker = QuotaTracker()
    for _ in range(20):
        tracker.record_request("groq_api")

    assert tracker.is_near_limit("groq_api") is True
    assert tracker.is_near_limit("some_other_provider") is False


def test_old_requests_outside_the_window_do_not_count(monkeypatch) -> None:
    import modules.ai_bridge.quota_tracker as quota_tracker_module

    fake_time = [1000.0]
    monkeypatch.setattr(quota_tracker_module.time, "monotonic", lambda: fake_time[0])
    tracker = QuotaTracker()
    for _ in range(20):
        tracker.record_request("groq_api")
    assert tracker.is_near_limit("groq_api") is True

    fake_time[0] += quota_tracker_module._WINDOW_SECONDS + 1

    assert tracker.is_near_limit("groq_api") is False


def test_is_near_limit_accepts_a_custom_limit() -> None:
    tracker = QuotaTracker()
    for _ in range(6):
        tracker.record_request("gemini_api")

    assert tracker.is_near_limit("gemini_api", limit=6) is True
    assert tracker.is_near_limit("gemini_api", limit=10) is False


# --- daily (persisted) tracking ---------------------------------------------


def _tracker(tmp_path) -> QuotaTracker:
    return QuotaTracker(daily_store=StateStore(db_path=tmp_path / "daily.db"))


def test_daily_count_starts_at_zero(tmp_path) -> None:
    assert _tracker(tmp_path).daily_count("gemini_api") == 0


def test_record_daily_request_increments_the_count(tmp_path) -> None:
    tracker = _tracker(tmp_path)
    tracker.record_daily_request("gemini_api")
    tracker.record_daily_request("gemini_api")

    assert tracker.daily_count("gemini_api") == 2


def test_daily_count_is_tracked_independently_per_provider(tmp_path) -> None:
    tracker = _tracker(tmp_path)
    tracker.record_daily_request("gemini_api")

    assert tracker.daily_count("gemini_api") == 1
    assert tracker.daily_count("claude_api") == 0


def test_is_near_daily_limit_false_below_the_limit(tmp_path) -> None:
    tracker = _tracker(tmp_path)
    tracker.record_daily_request("gemini_api")

    assert tracker.is_near_daily_limit("gemini_api", limit=400) is False


def test_is_near_daily_limit_true_at_the_limit(tmp_path) -> None:
    tracker = _tracker(tmp_path)
    for _ in range(3):
        tracker.record_daily_request("gemini_api")

    assert tracker.is_near_daily_limit("gemini_api", limit=3) is True


def test_daily_count_resets_on_a_new_day(tmp_path) -> None:
    store = StateStore(db_path=tmp_path / "daily.db")
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    store.set("gemini_api:date", yesterday)
    store.set("gemini_api:count", "999")

    tracker = QuotaTracker(daily_store=store)

    assert tracker.daily_count("gemini_api") == 0
