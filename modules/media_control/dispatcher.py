from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from core.dispatcher import CommandDispatcher
from modules.spotify_control import service_layer as spotify_service_layer
from modules.youtube_control import service_layer as youtube_service_layer

COMMAND_PAUSE = "media_pause"
COMMAND_RESUME = "media_resume"
COMMAND_NEXT = "media_next"

_NOTHING_PLAYING_MESSAGE = "Сейчас ничего не играет."
_NOTHING_LOADED_MESSAGE = "Сейчас ничего не открыто ни на YouTube, ни в Spotify."


async def _playing_services() -> list[str]:
    services = []
    if await youtube_service_layer.is_active():
        services.append("youtube")
    if await spotify_service_layer.is_active():
        services.append("spotify")
    return services


async def _loaded_services() -> list[str]:
    services = []
    if await youtube_service_layer.has_session():
        services.append("youtube")
    if await spotify_service_layer.has_session():
        services.append("spotify")
    return services


async def _run_for_each(services: list[str], actions: dict[str, Callable[[], Awaitable[str]]]) -> str:
    messages = [await actions[name]() for name in services]
    return " ".join(messages)


async def _pause(_params: dict[str, Any]) -> dict[str, Any]:
    services = await _playing_services()
    if not services:
        return {"message": _NOTHING_PLAYING_MESSAGE}
    message = await _run_for_each(
        services, {"youtube": youtube_service_layer.pause, "spotify": spotify_service_layer.pause}
    )
    return {"message": message}


async def _resume(_params: dict[str, Any]) -> dict[str, Any]:
    services = await _loaded_services()
    if not services:
        return {"message": _NOTHING_LOADED_MESSAGE}
    message = await _run_for_each(
        services, {"youtube": youtube_service_layer.resume, "spotify": spotify_service_layer.resume}
    )
    return {"message": message}


async def _next(_params: dict[str, Any]) -> dict[str, Any]:
    services = await _loaded_services()
    if not services:
        return {"message": _NOTHING_LOADED_MESSAGE}
    message = await _run_for_each(
        services, {"youtube": youtube_service_layer.next_video, "spotify": spotify_service_layer.next_track}
    )
    return {"message": message}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        COMMAND_PAUSE, _pause, description="Поставить на паузу то, что сейчас играет (видео или музыку)"
    )
    dispatcher.register(
        COMMAND_RESUME, _resume, description="Продолжить воспроизведение (видео или музыку)"
    )
    dispatcher.register(
        COMMAND_NEXT, _next, description="Переключить на следующее (видео или трек)"
    )
