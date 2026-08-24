from __future__ import annotations

import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

import httpx

from core.config import settings

_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
_TOKEN_URL = "https://accounts.spotify.com/api/token"
_REQUEST_TIMEOUT_SECONDS = 10.0

# user-modify-playback-state is what actually needs Premium (see
# modules/spotify_control/api_client.py's 403 handling) — the other two
# work fine on a free account, so "что сейчас играет" isn't gated behind a
# subscription the user might not have.
SCOPES = "user-modify-playback-state user-read-playback-state user-read-currently-playing"

# Keyed by the PKCE `state` value, cleared once consumed by the callback (or
# after _PENDING_TTL_SECONDS, in case the user never completes the login) —
# in-memory only, same reasoning as modules/ai_bridge/quota_tracker.py's
# per-minute window: a lost pending login after a process restart just means
# clicking "Войти" again, not a correctness problem.
_PENDING_TTL_SECONDS = 600.0
_pending_logins: dict[str, tuple[str, float]] = {}


class SpotifyOAuthError(RuntimeError):
    pass


def redirect_uri() -> str:
    return f"http://127.0.0.1:{settings.port}/api/spotify/callback"


def _generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)[:128]


def _code_challenge_for(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def start_login(client_id: str) -> str:
    """Registers a new pending PKCE login and returns the Spotify authorize
    URL to send the user's browser to. The `state` value doubles as CSRF
    protection for the callback below (see core/main.py's require_api_token
    docstring for why that route is exempt from the usual token check) and
    as the lookup key for the code_verifier this same flow generated."""
    code_verifier = _generate_code_verifier()
    state = secrets.token_urlsafe(24)
    _pending_logins[state] = (code_verifier, time.monotonic())

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "state": state,
        "scope": SCOPES,
        "code_challenge_method": "S256",
        "code_challenge": _code_challenge_for(code_verifier),
    }
    return f"{_AUTHORIZE_URL}?{urlencode(params)}"


def consume_pending_login(state: str) -> str | None:
    """The code_verifier for this `state`, or None if it's unknown/expired —
    the callback route must treat either the same way (reject the login)."""
    entry = _pending_logins.pop(state, None)
    if entry is None:
        return None
    code_verifier, created_at = entry
    if time.monotonic() - created_at > _PENDING_TTL_SECONDS:
        return None
    return code_verifier


async def exchange_code(code: str, code_verifier: str, client_id: str) -> dict[str, str]:
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(
            _TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri(),
                "client_id": client_id,
                "code_verifier": code_verifier,
            },
        )
    if response.status_code >= 400:
        raise SpotifyOAuthError(f"Spotify отказал в обмене кода на токен: {response.text}")
    return response.json()


async def refresh_access_token(refresh_token: str, client_id: str) -> dict[str, str]:
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(
            _TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id},
        )
    if response.status_code >= 400:
        raise SpotifyOAuthError(f"Не удалось обновить токен Spotify: {response.text}")
    return response.json()
