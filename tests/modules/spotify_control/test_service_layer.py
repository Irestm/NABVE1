from __future__ import annotations

import pytest

from modules.spotify_control import api_client, service_layer
from modules.spotify_control.domain import PlaybackState, TrackResult


async def test_search_and_play_returns_a_not_found_message_when_no_track(monkeypatch) -> None:
    monkeypatch.setattr(api_client, "search_track", lambda query: _none())

    message = await service_layer.search_and_play("что-то несуществующее")

    assert "не нашёл" in message.lower()


async def test_search_and_play_plays_the_found_track(monkeypatch) -> None:
    track = TrackResult(uri="spotify:track:abc", name="Song", artist="Artist")
    played: list[str] = []
    monkeypatch.setattr(api_client, "search_track", lambda query: _found(track))
    monkeypatch.setattr(api_client, "play", lambda uri: played.append(uri) or _noop())

    message = await service_layer.search_and_play("song")

    assert played == ["spotify:track:abc"]
    assert "Artist" in message and "Song" in message


async def test_pause_returns_a_confirmation_message(monkeypatch) -> None:
    monkeypatch.setattr(api_client, "pause", lambda: _noop())

    assert await service_layer.pause() == "Пауза."


async def test_now_playing_reports_nothing_playing(monkeypatch) -> None:
    monkeypatch.setattr(api_client, "get_playback_state", lambda: _none())

    message = await service_layer.now_playing()

    assert "ничего не играет" in message.lower()


async def test_now_playing_reports_the_current_track(monkeypatch) -> None:
    state = PlaybackState(track_name="Song", artist="Artist", is_playing=True)
    monkeypatch.setattr(api_client, "get_playback_state", lambda: _found(state))

    message = await service_layer.now_playing()

    assert "Artist" in message and "Song" in message


async def test_has_session_true_when_a_track_is_loaded(monkeypatch) -> None:
    state = PlaybackState(track_name="Song", artist="Artist", is_playing=False)
    monkeypatch.setattr(api_client, "get_playback_state", lambda: _found(state))

    assert await service_layer.has_session() is True


async def test_has_session_false_when_nothing_loaded(monkeypatch) -> None:
    monkeypatch.setattr(api_client, "get_playback_state", lambda: _none())

    assert await service_layer.has_session() is False


async def test_has_session_false_on_any_failure(monkeypatch) -> None:
    async def _raise() -> None:
        raise RuntimeError("not connected")

    monkeypatch.setattr(api_client, "get_playback_state", lambda: _raise())

    assert await service_layer.has_session() is False


async def test_is_active_true_only_when_playing(monkeypatch) -> None:
    playing = PlaybackState(track_name="Song", artist="Artist", is_playing=True)
    paused = PlaybackState(track_name="Song", artist="Artist", is_playing=False)

    monkeypatch.setattr(api_client, "get_playback_state", lambda: _found(playing))
    assert await service_layer.is_active() is True

    monkeypatch.setattr(api_client, "get_playback_state", lambda: _found(paused))
    assert await service_layer.is_active() is False


async def test_is_active_false_on_any_failure(monkeypatch) -> None:
    async def _raise() -> None:
        raise RuntimeError("not connected")

    monkeypatch.setattr(api_client, "get_playback_state", lambda: _raise())

    assert await service_layer.is_active() is False


async def _none():
    return None


async def _found(value):
    return value


async def _noop():
    return None
