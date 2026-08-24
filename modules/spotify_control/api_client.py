from __future__ import annotations

import httpx

from modules.spotify_control import token_store
from modules.spotify_control.domain import PlaybackState, TrackResult

_API_BASE = "https://api.spotify.com/v1"
_REQUEST_TIMEOUT_SECONDS = 10.0


class SpotifyApiError(RuntimeError):
    pass


class SpotifyNoActiveDeviceError(SpotifyApiError):
    pass


async def _headers() -> dict[str, str]:
    token = await token_store.get_access_token()
    return {"Authorization": f"Bearer {token}"}


def _raise_for_playback_error(response: httpx.Response) -> None:
    if response.status_code == 404:
        raise SpotifyNoActiveDeviceError(
            "Нет активного устройства Spotify — откройте приложение Spotify и запустите что-нибудь вручную один раз."
        )
    if response.status_code == 403:
        raise SpotifyApiError("Управление воспроизведением недоступно — нужен Spotify Premium.")
    if response.status_code >= 400:
        raise SpotifyApiError(f"Spotify API вернул ошибку: {response.text}")


async def search_track(query: str) -> TrackResult | None:
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.get(
            f"{_API_BASE}/search", headers=await _headers(), params={"q": query, "type": "track", "limit": 1}
        )
    response.raise_for_status()
    items = response.json().get("tracks", {}).get("items", [])
    if not items:
        return None
    item = items[0]
    artist = ", ".join(a["name"] for a in item.get("artists", []))
    return TrackResult(uri=item["uri"], name=item["name"], artist=artist)


async def play(track_uri: str) -> None:
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.put(
            f"{_API_BASE}/me/player/play", headers=await _headers(), json={"uris": [track_uri]}
        )
    _raise_for_playback_error(response)


async def pause() -> None:
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.put(f"{_API_BASE}/me/player/pause", headers=await _headers())
    _raise_for_playback_error(response)


async def resume() -> None:
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.put(f"{_API_BASE}/me/player/play", headers=await _headers())
    _raise_for_playback_error(response)


async def next_track() -> None:
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(f"{_API_BASE}/me/player/next", headers=await _headers())
    _raise_for_playback_error(response)


async def previous_track() -> None:
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(f"{_API_BASE}/me/player/previous", headers=await _headers())
    _raise_for_playback_error(response)


async def set_volume(percent: int) -> None:
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.put(
            f"{_API_BASE}/me/player/volume", headers=await _headers(), params={"volume_percent": percent}
        )
    _raise_for_playback_error(response)


async def get_playback_state() -> PlaybackState | None:
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.get(f"{_API_BASE}/me/player", headers=await _headers())
    if response.status_code == 204 or not response.content:
        return None
    response.raise_for_status()
    payload = response.json()
    item = payload.get("item")
    if item is None:
        return None
    artist = ", ".join(a["name"] for a in item.get("artists", []))
    return PlaybackState(track_name=item["name"], artist=artist, is_playing=bool(payload.get("is_playing")))
