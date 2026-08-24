from __future__ import annotations

import pytest

from modules.spotify_control import api_client


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, content: bytes = b"{}") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content
        self.text = str(payload)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.last_call: dict = {}

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, headers: dict, params: dict | None = None) -> _FakeResponse:
        self.last_call = {"method": "GET", "url": url, "headers": headers, "params": params}
        return self._response

    async def put(self, url: str, headers: dict, json: dict | None = None, params: dict | None = None) -> _FakeResponse:
        self.last_call = {"method": "PUT", "url": url, "headers": headers, "json": json, "params": params}
        return self._response

    async def post(self, url: str, headers: dict) -> _FakeResponse:
        self.last_call = {"method": "POST", "url": url, "headers": headers}
        return self._response


def _install(monkeypatch, response: _FakeResponse) -> _FakeAsyncClient:
    fake_client = _FakeAsyncClient(response)
    monkeypatch.setattr(api_client.httpx, "AsyncClient", lambda timeout: fake_client)
    monkeypatch.setattr(api_client.token_store, "get_access_token", lambda: _immediate_token())
    return fake_client


async def _immediate_token() -> str:
    return "fake-access-token"


async def test_search_track_returns_the_first_result(monkeypatch) -> None:
    response = _FakeResponse(
        200,
        {"tracks": {"items": [{"uri": "spotify:track:abc", "name": "Song", "artists": [{"name": "Artist"}]}]}},
    )
    _install(monkeypatch, response)

    track = await api_client.search_track("query")

    assert track is not None
    assert track.uri == "spotify:track:abc"
    assert track.name == "Song"
    assert track.artist == "Artist"


async def test_search_track_returns_none_when_no_results(monkeypatch) -> None:
    response = _FakeResponse(200, {"tracks": {"items": []}})
    _install(monkeypatch, response)

    assert await api_client.search_track("nothing") is None


async def test_play_sends_the_track_uri(monkeypatch) -> None:
    response = _FakeResponse(204)
    fake_client = _install(monkeypatch, response)

    await api_client.play("spotify:track:xyz")

    assert fake_client.last_call["json"] == {"uris": ["spotify:track:xyz"]}


async def test_pause_raises_no_active_device_on_404(monkeypatch) -> None:
    response = _FakeResponse(404)
    _install(monkeypatch, response)

    with pytest.raises(api_client.SpotifyNoActiveDeviceError):
        await api_client.pause()


async def test_resume_raises_a_clear_error_on_403_premium_required(monkeypatch) -> None:
    response = _FakeResponse(403)
    _install(monkeypatch, response)

    with pytest.raises(api_client.SpotifyApiError):
        await api_client.resume()


async def test_next_track_posts_to_the_next_endpoint(monkeypatch) -> None:
    response = _FakeResponse(204)
    fake_client = _install(monkeypatch, response)

    await api_client.next_track()

    assert fake_client.last_call["url"].endswith("/me/player/next")


async def test_set_volume_sends_the_percent_as_a_query_param(monkeypatch) -> None:
    response = _FakeResponse(204)
    fake_client = _install(monkeypatch, response)

    await api_client.set_volume(42)

    assert fake_client.last_call["params"] == {"volume_percent": 42}


async def test_get_playback_state_returns_none_on_204(monkeypatch) -> None:
    response = _FakeResponse(204, content=b"")
    _install(monkeypatch, response)

    assert await api_client.get_playback_state() is None


async def test_get_playback_state_parses_the_current_track(monkeypatch) -> None:
    response = _FakeResponse(
        200,
        {
            "is_playing": True,
            "item": {"name": "Song", "artists": [{"name": "Artist One"}, {"name": "Artist Two"}]},
        },
    )
    _install(monkeypatch, response)

    state = await api_client.get_playback_state()

    assert state is not None
    assert state.track_name == "Song"
    assert state.artist == "Artist One, Artist Two"
    assert state.is_playing is True
