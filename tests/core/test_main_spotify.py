from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import core.main as main_module
from core.config import settings
from core.main import app
from core.secret_store import SecretStoreUnavailableError
from modules.spotify_control import oauth as spotify_oauth
from modules.spotify_control import token_store as spotify_token_store

client = TestClient(app)
AUTH = {"X-Assistant-Token": settings.api_token}


@pytest.fixture(autouse=True)
def _fake_secret_store(monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setattr(spotify_token_store, "get_secret", lambda name: store.get(name))
    monkeypatch.setattr(spotify_token_store, "store_secret", lambda name, value: store.__setitem__(name, value))
    monkeypatch.setattr(spotify_token_store, "delete_secret", lambda name: store.pop(name, None))
    return store


def test_get_status_reports_nothing_configured_by_default() -> None:
    response = client.get("/api/spotify/status", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["client_id_configured"] is False
    assert body["connected"] is False


def test_save_client_id_reports_it_configured() -> None:
    response = client.post("/api/spotify/client_id", json={"client_id": "my-client-id"}, headers=AUTH)

    assert response.status_code == 200
    assert response.json()["client_id_configured"] is True


def test_save_client_id_rejects_empty_value() -> None:
    response = client.post("/api/spotify/client_id", json={"client_id": ""}, headers=AUTH)

    assert response.status_code == 422


def test_save_client_id_returns_500_when_secret_store_unavailable(monkeypatch) -> None:
    def _raise(name: str, value: str) -> None:
        raise SecretStoreUnavailableError("no keyring")

    monkeypatch.setattr(spotify_token_store, "store_secret", _raise)

    response = client.post("/api/spotify/client_id", json={"client_id": "my-client-id"}, headers=AUTH)

    assert response.status_code == 500


def test_start_login_requires_a_client_id_first() -> None:
    response = client.post("/api/spotify/login", headers=AUTH)

    assert response.status_code == 400


def test_start_login_returns_an_authorize_url() -> None:
    client.post("/api/spotify/client_id", json={"client_id": "my-client-id"}, headers=AUTH)

    response = client.post("/api/spotify/login", headers=AUTH)

    assert response.status_code == 200
    url = response.json()["authorize_url"]
    assert urlparse(url).netloc == "accounts.spotify.com"


def test_disconnect_clears_the_connection() -> None:
    client.post("/api/spotify/client_id", json={"client_id": "my-client-id"}, headers=AUTH)

    response = client.delete("/api/spotify/connection", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["client_id_configured"] is False


def test_status_without_auth_is_rejected() -> None:
    response = client.get("/api/spotify/status")

    assert response.status_code == 401


def test_callback_does_not_require_auth() -> None:
    response = client.get("/api/spotify/callback", params={"error": "access_denied"})

    assert response.status_code == 200


def test_callback_with_an_error_param_shows_a_message_and_does_not_store_anything() -> None:
    response = client.get("/api/spotify/callback", params={"error": "access_denied"})

    assert "отказал" in response.text.lower()


def test_callback_with_an_unknown_state_is_rejected() -> None:
    response = client.get("/api/spotify/callback", params={"code": "abc", "state": "never-issued"})

    assert response.status_code == 400


def test_callback_completes_the_login_and_stores_the_refresh_token(monkeypatch) -> None:
    client.post("/api/spotify/client_id", json={"client_id": "my-client-id"}, headers=AUTH)
    login_response = client.post("/api/spotify/login", headers=AUTH)
    state = parse_qs(urlparse(login_response.json()["authorize_url"]).query)["state"][0]

    async def fake_exchange_code(code: str, code_verifier: str, client_id: str) -> dict:
        assert code == "auth-code"
        assert client_id == "my-client-id"
        return {"access_token": "abc", "refresh_token": "the-refresh-token", "expires_in": 3600}

    monkeypatch.setattr(main_module.spotify_oauth, "exchange_code", fake_exchange_code)

    response = client.get("/api/spotify/callback", params={"code": "auth-code", "state": state})

    assert response.status_code == 200
    assert "подключён" in response.text.lower()
    assert spotify_token_store.get_refresh_token() == "the-refresh-token"


def test_callback_reports_a_failed_exchange(monkeypatch) -> None:
    client.post("/api/spotify/client_id", json={"client_id": "my-client-id"}, headers=AUTH)
    login_response = client.post("/api/spotify/login", headers=AUTH)
    state = parse_qs(urlparse(login_response.json()["authorize_url"]).query)["state"][0]

    async def fake_exchange_code(code: str, code_verifier: str, client_id: str) -> dict:
        raise spotify_oauth.SpotifyOAuthError("invalid_grant")

    monkeypatch.setattr(main_module.spotify_oauth, "exchange_code", fake_exchange_code)

    response = client.get("/api/spotify/callback", params={"code": "auth-code", "state": state})

    assert response.status_code == 200
    assert "не удалось" in response.text.lower()
