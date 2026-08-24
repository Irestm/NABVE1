from __future__ import annotations

import time

from core.secret_store import delete_secret, get_secret, store_secret
from modules.spotify_control import oauth

CLIENT_ID_SECRET_NAME = "spotify_client_id"
REFRESH_TOKEN_SECRET_NAME = "spotify_refresh_token"

_EXPIRY_MARGIN_SECONDS = 30.0

_access_token: str | None = None
_access_token_expiry: float = 0.0


class SpotifyNotConnectedError(RuntimeError):
    pass


def get_client_id() -> str | None:
    return get_secret(CLIENT_ID_SECRET_NAME)


def store_client_id(client_id: str) -> None:
    store_secret(CLIENT_ID_SECRET_NAME, client_id)


def get_refresh_token() -> str | None:
    return get_secret(REFRESH_TOKEN_SECRET_NAME)


def store_refresh_token(refresh_token: str) -> None:
    store_secret(REFRESH_TOKEN_SECRET_NAME, refresh_token)


def is_connected() -> bool:
    return get_client_id() is not None and get_refresh_token() is not None


def disconnect() -> None:
    global _access_token, _access_token_expiry
    delete_secret(CLIENT_ID_SECRET_NAME)
    delete_secret(REFRESH_TOKEN_SECRET_NAME)
    _access_token = None
    _access_token_expiry = 0.0


async def get_access_token() -> str:
    """The cached access token if it hasn't expired yet, else a fresh one
    via the stored refresh_token. Spotify sometimes rotates the refresh
    token on refresh and sometimes doesn't (both are valid per their docs);
    the new one is only persisted when one actually comes back, so the
    original keeps working otherwise."""
    global _access_token, _access_token_expiry
    if _access_token is not None and time.monotonic() < _access_token_expiry:
        return _access_token

    client_id = get_client_id()
    refresh_token = get_refresh_token()
    if not client_id or not refresh_token:
        raise SpotifyNotConnectedError("Spotify не подключён — сначала авторизуйтесь в настройках.")

    payload = await oauth.refresh_access_token(refresh_token, client_id)
    _access_token = payload["access_token"]
    _access_token_expiry = time.monotonic() + int(payload.get("expires_in", 3600)) - _EXPIRY_MARGIN_SECONDS
    new_refresh_token = payload.get("refresh_token")
    if new_refresh_token:
        store_refresh_token(new_refresh_token)
    return _access_token
