from __future__ import annotations

from modules.ai_bridge.quota_tracker import QuotaTracker


def test_not_near_limit_when_unused() -> None:
    tracker = QuotaTracker()
    assert tracker.is_near_limit("groq_api") is False


def test_near_limit_after_enough_requests_in_window() -> None:
    tracker = QuotaTracker()
    for _ in range(20):
        tracker.record_request("groq_api")
    assert tracker.is_near_limit("groq_api") is True


def test_providers_are_tracked_independently() -> None:
    tracker = QuotaTracker()
    for _ in range(20):
        tracker.record_request("groq_api")
    assert tracker.is_near_limit("gemini_api") is False


def test_old_requests_fall_out_of_the_window(monkeypatch) -> None:
    tracker = QuotaTracker()
    fake_time = [1000.0]
    monkeypatch.setattr("modules.ai_bridge.quota_tracker.time.monotonic", lambda: fake_time[0])

    for _ in range(20):
        tracker.record_request("groq_api")
    assert tracker.is_near_limit("groq_api") is True

    fake_time[0] += 61.0
    assert tracker.is_near_limit("groq_api") is False
