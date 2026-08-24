from __future__ import annotations

from typing import Any

from core.dispatcher import CommandDispatcher
from modules.spotify_control import service_layer

COMMAND_SEARCH_AND_PLAY = "spotify_search_and_play"
COMMAND_PAUSE = "spotify_pause"
COMMAND_RESUME = "spotify_resume"
COMMAND_NEXT = "spotify_next"
COMMAND_PREVIOUS = "spotify_previous"
COMMAND_SET_VOLUME = "spotify_set_volume"
COMMAND_NOW_PLAYING = "spotify_now_playing"


async def _search_and_play(params: dict[str, Any]) -> dict[str, Any]:
    return {"message": await service_layer.search_and_play(params["query"])}


async def _pause(_params: dict[str, Any]) -> dict[str, Any]:
    return {"message": await service_layer.pause()}


async def _resume(_params: dict[str, Any]) -> dict[str, Any]:
    return {"message": await service_layer.resume()}


async def _next(_params: dict[str, Any]) -> dict[str, Any]:
    return {"message": await service_layer.next_track()}


async def _previous(_params: dict[str, Any]) -> dict[str, Any]:
    return {"message": await service_layer.previous_track()}


async def _set_volume(params: dict[str, Any]) -> dict[str, Any]:
    return {"message": await service_layer.set_volume(int(params["percent"]))}


async def _now_playing(_params: dict[str, Any]) -> dict[str, Any]:
    return {"message": await service_layer.now_playing()}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(COMMAND_SEARCH_AND_PLAY, _search_and_play, description="Найти и включить трек в Spotify")
    dispatcher.register(COMMAND_PAUSE, _pause, description="Поставить Spotify на паузу")
    dispatcher.register(COMMAND_RESUME, _resume, description="Продолжить воспроизведение в Spotify")
    dispatcher.register(COMMAND_NEXT, _next, description="Следующий трек в Spotify")
    dispatcher.register(COMMAND_PREVIOUS, _previous, description="Предыдущий трек в Spotify")
    dispatcher.register(COMMAND_SET_VOLUME, _set_volume, description="Задать громкость в Spotify")
    dispatcher.register(COMMAND_NOW_PLAYING, _now_playing, description="Сказать, что сейчас играет в Spotify")
