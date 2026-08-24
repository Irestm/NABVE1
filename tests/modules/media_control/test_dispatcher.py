from __future__ import annotations

from core.dispatcher import CommandDispatcher
from modules.media_control import dispatcher as media_dispatcher
from modules.spotify_control import service_layer as spotify_service_layer
from modules.youtube_control import service_layer as youtube_service_layer


def test_register_commands_registers_every_command() -> None:
    dispatcher = CommandDispatcher()

    media_dispatcher.register_commands(dispatcher)

    names = {c.name for c in dispatcher.list_commands()}
    assert names == {media_dispatcher.COMMAND_PAUSE, media_dispatcher.COMMAND_RESUME, media_dispatcher.COMMAND_NEXT}


def _async_true():
    async def _fn() -> bool:
        return True

    return _fn


def _async_false():
    async def _fn() -> bool:
        return False

    return _fn


async def test_pause_says_nothing_playing_when_neither_service_is_active(monkeypatch) -> None:
    monkeypatch.setattr(youtube_service_layer, "is_active", _async_false())
    monkeypatch.setattr(spotify_service_layer, "is_active", _async_false())

    result = await media_dispatcher._pause({})

    assert result == {"message": media_dispatcher._NOTHING_PLAYING_MESSAGE}


async def test_pause_pauses_only_youtube_when_only_youtube_is_playing(monkeypatch) -> None:
    monkeypatch.setattr(youtube_service_layer, "is_active", _async_true())
    monkeypatch.setattr(spotify_service_layer, "is_active", _async_false())

    async def fake_youtube_pause() -> str:
        return "YouTube пауза."

    async def fake_spotify_pause() -> str:
        raise AssertionError("Spotify should not have been paused")

    monkeypatch.setattr(youtube_service_layer, "pause", fake_youtube_pause)
    monkeypatch.setattr(spotify_service_layer, "pause", fake_spotify_pause)

    result = await media_dispatcher._pause({})

    assert result == {"message": "YouTube пауза."}


async def test_pause_pauses_both_when_both_are_playing(monkeypatch) -> None:
    monkeypatch.setattr(youtube_service_layer, "is_active", _async_true())
    monkeypatch.setattr(spotify_service_layer, "is_active", _async_true())

    async def fake_youtube_pause() -> str:
        return "YouTube пауза."

    async def fake_spotify_pause() -> str:
        return "Spotify пауза."

    monkeypatch.setattr(youtube_service_layer, "pause", fake_youtube_pause)
    monkeypatch.setattr(spotify_service_layer, "pause", fake_spotify_pause)

    result = await media_dispatcher._pause({})

    assert result == {"message": "YouTube пауза. Spotify пауза."}


async def test_resume_says_nothing_loaded_when_neither_service_has_a_session(monkeypatch) -> None:
    monkeypatch.setattr(youtube_service_layer, "has_session", _async_false())
    monkeypatch.setattr(spotify_service_layer, "has_session", _async_false())

    result = await media_dispatcher._resume({})

    assert result == {"message": media_dispatcher._NOTHING_LOADED_MESSAGE}


async def test_resume_resumes_the_loaded_service(monkeypatch) -> None:
    monkeypatch.setattr(youtube_service_layer, "has_session", _async_false())
    monkeypatch.setattr(spotify_service_layer, "has_session", _async_true())

    async def fake_spotify_resume() -> str:
        return "Spotify продолжает."

    monkeypatch.setattr(spotify_service_layer, "resume", fake_spotify_resume)

    result = await media_dispatcher._resume({})

    assert result == {"message": "Spotify продолжает."}


async def test_next_skips_on_the_loaded_service(monkeypatch) -> None:
    monkeypatch.setattr(youtube_service_layer, "has_session", _async_true())
    monkeypatch.setattr(spotify_service_layer, "has_session", _async_false())

    async def fake_youtube_next() -> str:
        return "Следующее видео."

    monkeypatch.setattr(youtube_service_layer, "next_video", fake_youtube_next)

    result = await media_dispatcher._next({})

    assert result == {"message": "Следующее видео."}
