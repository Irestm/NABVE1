from __future__ import annotations

from modules.ai_bridge.quota_tracker import QuotaTracker


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
