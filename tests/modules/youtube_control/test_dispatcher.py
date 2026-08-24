from __future__ import annotations

from core.dispatcher import CommandDispatcher
from modules.youtube_control import dispatcher as youtube_dispatcher
from modules.youtube_control import service_layer


def test_register_youtube_commands_registers_every_command() -> None:
    dispatcher = CommandDispatcher()

    youtube_dispatcher.register_commands(dispatcher)

    names = {c.name for c in dispatcher.list_commands()}
    assert names == {
        youtube_dispatcher.COMMAND_SEARCH_AND_PLAY,
        youtube_dispatcher.COMMAND_PAUSE,
        youtube_dispatcher.COMMAND_RESUME,
        youtube_dispatcher.COMMAND_NEXT,
        youtube_dispatcher.COMMAND_SEEK,
        youtube_dispatcher.COMMAND_SET_VOLUME,
        youtube_dispatcher.COMMAND_SET_SPEED,
    }


async def test_search_and_play_handler_delegates_to_service_layer(monkeypatch) -> None:
    async def fake_search_and_play(query: str) -> str:
        assert query == "лоу фай бит"
        return "Включаю: лоу фай бит."

    monkeypatch.setattr(service_layer, "search_and_play", fake_search_and_play)

    result = await youtube_dispatcher._search_and_play({"query": "лоу фай бит"})

    assert result == {"message": "Включаю: лоу фай бит."}


async def test_seek_handler_converts_offset_to_int(monkeypatch) -> None:
    seen = {}

    async def fake_seek(offset_seconds: int) -> str:
        seen["offset_seconds"] = offset_seconds
        return "Перемотал."

    monkeypatch.setattr(service_layer, "seek", fake_seek)

    result = await youtube_dispatcher._seek({"offset_seconds": "10"})

    assert seen["offset_seconds"] == 10
    assert isinstance(seen["offset_seconds"], int)
    assert result == {"message": "Перемотал."}


async def test_set_volume_handler_converts_percent_to_int(monkeypatch) -> None:
    seen = {}

    async def fake_set_volume(percent: int) -> str:
        seen["percent"] = percent
        return "Громкость."

    monkeypatch.setattr(service_layer, "set_volume", fake_set_volume)

    await youtube_dispatcher._set_volume({"percent": "55"})

    assert seen["percent"] == 55


async def test_set_speed_handler_converts_rate_to_float(monkeypatch) -> None:
    seen = {}

    async def fake_set_speed(rate: float) -> str:
        seen["rate"] = rate
        return "Скорость."

    monkeypatch.setattr(service_layer, "set_speed", fake_set_speed)

    await youtube_dispatcher._set_speed({"rate": "1.5"})

    assert seen["rate"] == 1.5


async def test_pause_handler_delegates_to_service_layer(monkeypatch) -> None:
    async def fake_pause() -> str:
        return "Пауза."

    monkeypatch.setattr(service_layer, "pause", fake_pause)

    result = await youtube_dispatcher._pause({})

    assert result == {"message": "Пауза."}
