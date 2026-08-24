from __future__ import annotations

from typing import Any

import pytest

from modules.ai_bridge.state_store import StateStore
from modules.youtube_control import api_client, service_layer
from modules.youtube_control.domain import VideoResult
from modules.youtube_control.quota_tracker import QuotaTracker


class _FakeBrowserSession:
    def __init__(self) -> None:
        self.opened_video_ids: list[str] = []
        self.search_queries: list[str] = []
        self.control_calls: list[tuple[str, dict[str, Any]]] = []
        self.search_result_title = "Найдено в браузере"

    async def open_video(self, video_id: str) -> None:
        self.opened_video_ids.append(video_id)

    async def search_and_open(self, query: str) -> str:
        self.search_queries.append(query)
        return self.search_result_title

    async def control(self, action: str, params: dict[str, Any]) -> None:
        self.control_calls.append((action, params))


@pytest.fixture(autouse=True)
def _isolated_quota_tracker(monkeypatch, tmp_path) -> QuotaTracker:
    tracker = QuotaTracker(store=StateStore(db_path=tmp_path / "state.db"))
    monkeypatch.setattr(service_layer, "_quota_tracker", tracker)
    return tracker


@pytest.fixture
def fake_session(monkeypatch) -> _FakeBrowserSession:
    session = _FakeBrowserSession()
    monkeypatch.setattr(service_layer.browser_control, "get_session", lambda: session)
    return session


async def test_search_and_play_uses_the_api_when_a_key_is_present(monkeypatch, fake_session) -> None:
    monkeypatch.setattr(service_layer, "get_secret", lambda name: "my-api-key")

    async def fake_search_video(api_key: str, query: str) -> VideoResult:
        return VideoResult(video_id="xyz789", title="API видео")

    monkeypatch.setattr(service_layer.api_client, "search_video", fake_search_video)

    message = await service_layer.search_and_play("что-нибудь")

    assert fake_session.opened_video_ids == ["xyz789"]
    assert fake_session.search_queries == []
    assert "API видео" in message


async def test_search_and_play_records_quota_usage_on_api_success(
    monkeypatch, fake_session, _isolated_quota_tracker
) -> None:
    monkeypatch.setattr(service_layer, "get_secret", lambda name: "my-api-key")

    async def fake_search_video(api_key: str, query: str) -> VideoResult:
        return VideoResult(video_id="xyz789", title="API видео")

    monkeypatch.setattr(service_layer.api_client, "search_video", fake_search_video)

    await service_layer.search_and_play("что-нибудь")

    assert _isolated_quota_tracker.units_used() == api_client.SEARCH_COST_UNITS


async def test_search_and_play_falls_back_to_browser_without_a_key(monkeypatch, fake_session) -> None:
    monkeypatch.setattr(service_layer, "get_secret", lambda name: None)

    message = await service_layer.search_and_play("лоу фай бит")

    assert fake_session.search_queries == ["лоу фай бит"]
    assert fake_session.opened_video_ids == []
    assert "Найдено в браузере" in message


async def test_search_and_play_falls_back_to_browser_when_api_errors(monkeypatch, fake_session) -> None:
    monkeypatch.setattr(service_layer, "get_secret", lambda name: "my-api-key")

    async def fake_search_video(api_key: str, query: str):
        raise api_client.YouTubeApiError("quota exceeded")

    monkeypatch.setattr(service_layer.api_client, "search_video", fake_search_video)

    message = await service_layer.search_and_play("что-нибудь")

    assert fake_session.search_queries == ["что-нибудь"]
    assert "Найдено в браузере" in message


async def test_search_and_play_skips_the_api_when_quota_is_already_exhausted(
    monkeypatch, fake_session, _isolated_quota_tracker
) -> None:
    monkeypatch.setattr(service_layer, "get_secret", lambda name: "my-api-key")
    _isolated_quota_tracker.record_usage(_isolated_quota_tracker.status().daily_limit)

    called = False

    async def fake_search_video(api_key: str, query: str):
        nonlocal called
        called = True

    monkeypatch.setattr(service_layer.api_client, "search_video", fake_search_video)

    await service_layer.search_and_play("что-нибудь")

    assert called is False
    assert fake_session.search_queries == ["что-нибудь"]


async def test_search_and_play_appends_the_near_limit_warning_once(
    monkeypatch, fake_session, _isolated_quota_tracker
) -> None:
    monkeypatch.setattr(service_layer, "get_secret", lambda name: None)
    _isolated_quota_tracker.record_usage(int(_isolated_quota_tracker.status().daily_limit * 0.8))

    first_message = await service_layer.search_and_play("запрос один")
    second_message = await service_layer.search_and_play("запрос два")

    assert "лимит" in first_message.lower()
    assert "лимит" not in second_message.lower()


async def test_pause_calls_browser_control_with_pause_action(fake_session) -> None:
    message = await service_layer.pause()

    assert fake_session.control_calls == [("pause", {})]
    assert message == "Пауза."


async def test_resume_calls_browser_control_with_resume_action(fake_session) -> None:
    await service_layer.resume()

    assert fake_session.control_calls == [("resume", {})]


async def test_next_video_calls_browser_control_with_next_action(fake_session) -> None:
    await service_layer.next_video()

    assert fake_session.control_calls == [("next", {})]


async def test_seek_passes_the_offset_in_seconds(fake_session) -> None:
    await service_layer.seek(-15)

    assert fake_session.control_calls == [("seek", {"offset_seconds": -15})]


async def test_set_volume_passes_the_percent(fake_session) -> None:
    await service_layer.set_volume(70)

    assert fake_session.control_calls == [("set_volume", {"percent": 70})]


async def test_set_speed_passes_the_rate(fake_session) -> None:
    await service_layer.set_speed(1.5)

    assert fake_session.control_calls == [("set_speed", {"rate": 1.5})]


async def test_has_session_delegates_to_browser_control(monkeypatch) -> None:
    monkeypatch.setattr(service_layer.browser_control, "has_loaded_video", lambda: True)

    assert await service_layer.has_session() is True


async def test_is_active_delegates_to_browser_control(monkeypatch) -> None:
    async def fake_is_playing() -> bool:
        return True

    monkeypatch.setattr(service_layer.browser_control, "is_playing", fake_is_playing)

    assert await service_layer.is_active() is True
