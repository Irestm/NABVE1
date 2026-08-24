from __future__ import annotations

from modules.spotify_control import api_client


async def search_and_play(query: str) -> str:
    track = await api_client.search_track(query)
    if track is None:
        return f"Не нашёл в Spotify ничего по запросу «{query}»."
    await api_client.play(track.uri)
    return f"Включаю в Spotify: {track.artist} — {track.name}."


async def pause() -> str:
    await api_client.pause()
    return "Пауза."


async def resume() -> str:
    await api_client.resume()
    return "Продолжаю."


async def next_track() -> str:
    await api_client.next_track()
    return "Следующий трек."


async def previous_track() -> str:
    await api_client.previous_track()
    return "Предыдущий трек."


async def set_volume(percent: int) -> str:
    await api_client.set_volume(percent)
    return f"Громкость {percent} процентов."


async def now_playing() -> str:
    state = await api_client.get_playback_state()
    if state is None:
        return "Сейчас ничего не играет."
    verb = "играет" if state.is_playing else "на паузе"
    return f"Сейчас {verb}: {state.artist} — {state.track_name}."


async def has_session() -> bool:
    """Whether Spotify has anything loaded at all (playing or paused) —
    used by modules.media_control to decide whether a bare "продолжи"/
    "следующее" should act on Spotify. Best-effort: any failure (not
    connected, expired token, network) just means "nothing here", not an
    error the coordinator needs to surface."""
    try:
        state = await api_client.get_playback_state()
    except Exception:
        return False
    return state is not None


async def is_active() -> bool:
    """Whether Spotify is actually making sound right now — used by
    modules.media_control to decide which service a bare "пауза" should
    act on. Same best-effort-false-on-any-failure reasoning as
    has_session()."""
    try:
        state = await api_client.get_playback_state()
    except Exception:
        return False
    return state is not None and state.is_playing
