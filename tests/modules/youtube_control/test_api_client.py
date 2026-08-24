from __future__ import annotations

import pytest

from modules.youtube_control import api_client


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.last_params: dict | None = None

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, params: dict) -> _FakeResponse:
        self.last_params = params
        return self._response


def _install_fake_client(monkeypatch, response: _FakeResponse) -> _FakeAsyncClient:
    fake_client = _FakeAsyncClient(response)
    monkeypatch.setattr(api_client.httpx, "AsyncClient", lambda timeout: fake_client)
    return fake_client


async def test_search_video_returns_first_result(monkeypatch) -> None:
    response = _FakeResponse(
        200,
        {"items": [{"id": {"videoId": "abc123"}, "snippet": {"title": "Some Video"}}]},
    )
    _install_fake_client(monkeypatch, response)

    result = await api_client.search_video("key", "some query")

    assert result is not None
    assert result.video_id == "abc123"
    assert result.title == "Some Video"
    assert result.url == "https://www.youtube.com/watch?v=abc123"


async def test_search_video_returns_none_when_no_items(monkeypatch) -> None:
    response = _FakeResponse(200, {"items": []})
    _install_fake_client(monkeypatch, response)

    assert await api_client.search_video("key", "nothing") is None


async def test_search_video_raises_youtube_api_error_on_403(monkeypatch) -> None:
    response = _FakeResponse(403, {})
    _install_fake_client(monkeypatch, response)

    with pytest.raises(api_client.YouTubeApiError):
        await api_client.search_video("bad-key", "query")


async def test_search_video_sends_the_api_key_and_query(monkeypatch) -> None:
    response = _FakeResponse(200, {"items": []})
    fake_client = _install_fake_client(monkeypatch, response)

    await api_client.search_video("my-key", "лоу фай бит")

    assert fake_client.last_params["key"] == "my-key"
    assert fake_client.last_params["q"] == "лоу фай бит"
