from __future__ import annotations

import pytest

from modules.spotify_control import token_store


@pytest.fixture(autouse=True)
def _reset_access_token_cache(monkeypatch) -> None:
    monkeypatch.setattr(token_store, "_access_token", None)
    monkeypatch.setattr(token_store, "_access_token_expiry", 0.0)


@pytest.fixture
def _fake_secret_store(monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setattr(token_store, "get_secret", lambda name: store.get(name))
    monkeypatch.setattr(token_store, "store_secret", lambda name, value: store.__setitem__(name, value))

    def _delete(name: str) -> None:
        store.pop(name, None)

    monkeypatch.setattr(token_store, "delete_secret", _delete)
    return store


def test_is_connected_false_when_nothing_stored(_fake_secret_store) -> None:
    assert token_store.is_connected() is False


def test_is_connected_false_with_only_a_client_id(_fake_secret_store) -> None:
    token_store.store_client_id("client-id")

    assert token_store.is_connected() is False


def test_is_connected_true_with_both_stored(_fake_secret_store) -> None:
    token_store.store_client_id("client-id")
    token_store.store_refresh_token("refresh-token")

    assert token_store.is_connected() is True


def test_disconnect_clears_both_and_the_cached_access_token(_fake_secret_store) -> None:
    token_store.store_client_id("client-id")
    token_store.store_refresh_token("refresh-token")
    token_store._access_token = "cached"
    token_store._access_token_expiry = 9999999999.0

    token_store.disconnect()

    assert token_store.is_connected() is False
    assert token_store._access_token is None


async def test_get_access_token_raises_when_not_connected(_fake_secret_store) -> None:
    with pytest.raises(token_store.SpotifyNotConnectedError):
        await token_store.get_access_token()


async def test_get_access_token_refreshes_and_caches(monkeypatch, _fake_secret_store) -> None:
    token_store.store_client_id("client-id")
    token_store.store_refresh_token("refresh-token")

    async def fake_refresh(refresh_token: str, client_id: str) -> dict:
        assert refresh_token == "refresh-token"
        assert client_id == "client-id"
        return {"access_token": "fresh-token", "expires_in": 3600}

    monkeypatch.setattr(token_store.oauth, "refresh_access_token", fake_refresh)

    token = await token_store.get_access_token()

    assert token == "fresh-token"


async def test_get_access_token_reuses_the_cached_token_without_refreshing(monkeypatch, _fake_secret_store) -> None:
    token_store.store_client_id("client-id")
    token_store.store_refresh_token("refresh-token")
    calls = {"n": 0}

    async def fake_refresh(refresh_token: str, client_id: str) -> dict:
        calls["n"] += 1
        return {"access_token": "fresh-token", "expires_in": 3600}

    monkeypatch.setattr(token_store.oauth, "refresh_access_token", fake_refresh)

    first = await token_store.get_access_token()
    second = await token_store.get_access_token()

    assert first == second
    assert calls["n"] == 1


async def test_get_access_token_stores_a_rotated_refresh_token(monkeypatch, _fake_secret_store) -> None:
    token_store.store_client_id("client-id")
    token_store.store_refresh_token("old-refresh-token")

    async def fake_refresh(refresh_token: str, client_id: str) -> dict:
        return {"access_token": "fresh-token", "expires_in": 3600, "refresh_token": "new-refresh-token"}

    monkeypatch.setattr(token_store.oauth, "refresh_access_token", fake_refresh)

    await token_store.get_access_token()

    assert token_store.get_refresh_token() == "new-refresh-token"


async def test_get_access_token_keeps_the_old_refresh_token_when_none_is_returned(
    monkeypatch, _fake_secret_store
) -> None:
    token_store.store_client_id("client-id")
    token_store.store_refresh_token("old-refresh-token")

    async def fake_refresh(refresh_token: str, client_id: str) -> dict:
        return {"access_token": "fresh-token", "expires_in": 3600}

    monkeypatch.setattr(token_store.oauth, "refresh_access_token", fake_refresh)

    await token_store.get_access_token()

    assert token_store.get_refresh_token() == "old-refresh-token"
