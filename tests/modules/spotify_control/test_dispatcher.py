from __future__ import annotations

from core.dispatcher import CommandDispatcher
from modules.spotify_control import dispatcher as spotify_dispatcher
from modules.spotify_control import service_layer


def test_register_commands_registers_every_command() -> None:
    dispatcher = CommandDispatcher()

    spotify_dispatcher.register_commands(dispatcher)

    names = {c.name for c in dispatcher.list_commands()}
    assert names == {
        spotify_dispatcher.COMMAND_SEARCH_AND_PLAY,
        spotify_dispatcher.COMMAND_PAUSE,
        spotify_dispatcher.COMMAND_RESUME,
        spotify_dispatcher.COMMAND_NEXT,
        spotify_dispatcher.COMMAND_PREVIOUS,
        spotify_dispatcher.COMMAND_SET_VOLUME,
        spotify_dispatcher.COMMAND_NOW_PLAYING,
    }


async def test_search_and_play_handler_delegates_to_service_layer(monkeypatch) -> None:
    async def fake_search_and_play(query: str) -> str:
        assert query == "лоу фай бит"
        return "Включаю: лоу фай бит."

    monkeypatch.setattr(service_layer, "search_and_play", fake_search_and_play)

    result = await spotify_dispatcher._search_and_play({"query": "лоу фай бит"})

    assert result == {"message": "Включаю: лоу фай бит."}


async def test_set_volume_handler_converts_percent_to_int(monkeypatch) -> None:
    seen = {}

    async def fake_set_volume(percent: int) -> str:
        seen["percent"] = percent
        return "Громкость."

    monkeypatch.setattr(service_layer, "set_volume", fake_set_volume)

    await spotify_dispatcher._set_volume({"percent": "55"})

    assert seen["percent"] == 55
    assert isinstance(seen["percent"], int)


async def test_pause_handler_delegates_to_service_layer(monkeypatch) -> None:
    async def fake_pause() -> str:
        return "Пауза."

    monkeypatch.setattr(service_layer, "pause", fake_pause)

    result = await spotify_dispatcher._pause({})

    assert result == {"message": "Пауза."}
