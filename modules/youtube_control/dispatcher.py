from __future__ import annotations

from typing import Any

from core.dispatcher import CommandDispatcher
from modules.youtube_control import service_layer

COMMAND_SEARCH_AND_PLAY = "youtube_search_and_play"
COMMAND_PAUSE = "youtube_pause"
COMMAND_RESUME = "youtube_resume"
COMMAND_NEXT = "youtube_next"
COMMAND_SEEK = "youtube_seek"
COMMAND_SET_VOLUME = "youtube_set_volume"
COMMAND_SET_SPEED = "youtube_set_speed"


async def _search_and_play(params: dict[str, Any]) -> dict[str, Any]:
    return {"message": await service_layer.search_and_play(params["query"])}


async def _pause(_params: dict[str, Any]) -> dict[str, Any]:
    return {"message": await service_layer.pause()}


async def _resume(_params: dict[str, Any]) -> dict[str, Any]:
    return {"message": await service_layer.resume()}


async def _next(_params: dict[str, Any]) -> dict[str, Any]:
    return {"message": await service_layer.next_video()}


async def _seek(params: dict[str, Any]) -> dict[str, Any]:
    return {"message": await service_layer.seek(int(params["offset_seconds"]))}


async def _set_volume(params: dict[str, Any]) -> dict[str, Any]:
    return {"message": await service_layer.set_volume(int(params["percent"]))}


async def _set_speed(params: dict[str, Any]) -> dict[str, Any]:
    return {"message": await service_layer.set_speed(float(params["rate"]))}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        COMMAND_SEARCH_AND_PLAY, _search_and_play, description="Найти и включить видео на YouTube"
    )
    dispatcher.register(COMMAND_PAUSE, _pause, description="Поставить видео на YouTube на паузу")
    dispatcher.register(COMMAND_RESUME, _resume, description="Продолжить воспроизведение на YouTube")
    dispatcher.register(COMMAND_NEXT, _next, description="Переключить на следующее видео на YouTube")
    dispatcher.register(COMMAND_SEEK, _seek, description="Перемотать видео на YouTube")
    dispatcher.register(COMMAND_SET_VOLUME, _set_volume, description="Задать громкость видео на YouTube")
    dispatcher.register(COMMAND_SET_SPEED, _set_speed, description="Задать скорость воспроизведения на YouTube")
