from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from modules.spotify_control import oauth


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.last_data: dict | None = None

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, data: dict) -> _FakeResponse:
        self.last_data = data
        return self._response


def _install_fake_client(monkeypatch, response: _FakeResponse) -> _FakeAsyncClient:
    fake_client = _FakeAsyncClient(response)
    monkeypatch.setattr(oauth.httpx, "AsyncClient", lambda timeout: fake_client)
    return fake_client


def test_start_login_returns_an_authorize_url_with_pkce_params() -> None:
    url = oauth.start_login("my-client-id")

    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.spotify.com"
    assert params["client_id"] == ["my-client-id"]
    assert params["response_type"] == ["code"]
    assert params["code_challenge_method"] == ["S256"]
    assert "code_challenge" in params
    assert "state" in params


def test_start_login_registers_a_consumable_pending_login() -> None:
    url = oauth.start_login("my-client-id")
    state = parse_qs(urlparse(url).query)["state"][0]

    code_verifier = oauth.consume_pending_login(state)

    assert code_verifier is not None
    assert len(code_verifier) >= 43


def test_consume_pending_login_returns_none_for_an_unknown_state() -> None:
    assert oauth.consume_pending_login("never-issued") is None


def test_consume_pending_login_can_only_be_used_once() -> None:
    url = oauth.start_login("my-client-id")
    state = parse_qs(urlparse(url).query)["state"][0]

    first = oauth.consume_pending_login(state)
    second = oauth.consume_pending_login(state)

    assert first is not None
    assert second is None


def test_consume_pending_login_rejects_an_expired_entry(monkeypatch) -> None:
    url = oauth.start_login("my-client-id")
    state = parse_qs(urlparse(url).query)["state"][0]

    real_monotonic = oauth.time.monotonic
    monkeypatch.setattr(oauth.time, "monotonic", lambda: real_monotonic() + oauth._PENDING_TTL_SECONDS + 1)

    assert oauth.consume_pending_login(state) is None


@pytest.mark.asyncio
async def test_exchange_code_returns_the_token_payload(monkeypatch) -> None:
    response = _FakeResponse(200, {"access_token": "abc", "refresh_token": "def", "expires_in": 3600})
    _install_fake_client(monkeypatch, response)

    payload = await oauth.exchange_code("code123", "verifier123", "client-id")

    assert payload["access_token"] == "abc"


@pytest.mark.asyncio
async def test_exchange_code_raises_on_error_response(monkeypatch) -> None:
    response = _FakeResponse(400, {"error": "invalid_grant"})
    _install_fake_client(monkeypatch, response)

    with pytest.raises(oauth.SpotifyOAuthError):
        await oauth.exchange_code("bad-code", "verifier123", "client-id")


@pytest.mark.asyncio
async def test_refresh_access_token_sends_the_refresh_grant(monkeypatch) -> None:
    response = _FakeResponse(200, {"access_token": "new-token", "expires_in": 3600})
    fake_client = _install_fake_client(monkeypatch, response)

    await oauth.refresh_access_token("my-refresh-token", "client-id")

    assert fake_client.last_data["grant_type"] == "refresh_token"
    assert fake_client.last_data["refresh_token"] == "my-refresh-token"


@pytest.mark.asyncio
async def test_refresh_access_token_raises_on_error_response(monkeypatch) -> None:
    response = _FakeResponse(400, {"error": "invalid_grant"})
    _install_fake_client(monkeypatch, response)

    with pytest.raises(oauth.SpotifyOAuthError):
        await oauth.refresh_access_token("bad-refresh-token", "client-id")
