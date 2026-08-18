from __future__ import annotations

import asyncio
from typing import Any

from core.dispatcher import CommandDispatcher
from modules.user_profile import service_layer
from modules.user_profile.communication_styles import COMMUNICATION_STYLES
from modules.user_profile.uow import ProfileUnitOfWork


async def _handle_profile_set(params: dict[str, Any]) -> dict[str, Any]:
    key = params.get("key")
    value = params.get("value")
    if not key:
        raise ValueError("Не указан ключ.")
    if value is None:
        raise ValueError("Не указано значение.")
    await asyncio.to_thread(service_layer.set_fact, ProfileUnitOfWork(), key, value)
    return {"key": key, "stored": True}


async def _handle_profile_get(params: dict[str, Any]) -> dict[str, Any]:
    key = params.get("key")
    if not key:
        raise ValueError("Не указан ключ.")
    value = await asyncio.to_thread(service_layer.get_fact, ProfileUnitOfWork(), key)
    return {"key": key, "value": value}


async def _handle_profile_delete(params: dict[str, Any]) -> dict[str, Any]:
    key = params.get("key")
    if not key:
        raise ValueError("Не указан ключ.")
    deleted = await asyncio.to_thread(service_layer.delete_fact, ProfileUnitOfWork(), key)
    return {"key": key, "deleted": deleted}


async def _handle_profile_forget(params: dict[str, Any]) -> dict[str, Any]:
    key = params.get("key")
    if not key:
        raise ValueError("Не указан ключ.")
    forgotten = await asyncio.to_thread(service_layer.forget, ProfileUnitOfWork(), key)
    return {"key": key, "forgotten": forgotten}


async def _handle_profile_list_keys(_params: dict[str, Any]) -> dict[str, Any]:
    keys = await asyncio.to_thread(service_layer.list_keys, ProfileUnitOfWork())
    return {"keys": keys}


async def _handle_profile_save_about_me(params: dict[str, Any]) -> dict[str, Any]:
    text = params.get("text")
    if not text:
        raise ValueError("Не указан текст.")
    extracted_keys = await asyncio.to_thread(service_layer.save_about_me, ProfileUnitOfWork(), text)
    return {"stored": True, "extracted_keys": extracted_keys}


async def _handle_list_communication_styles(_params: dict[str, Any]) -> dict[str, Any]:
    return {
        "styles": [
            {"key": style.key, "label": style.label, "prosody_rate": style.prosody_rate}
            for style in COMMUNICATION_STYLES
        ]
    }


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "profile_set",
        _handle_profile_set,
        dangerous=False,
        description="Сохранить зашифрованную запись ключ-значение в профиле пользователя (key, value).",
    )
    dispatcher.register(
        "profile_get",
        _handle_profile_get,
        dangerous=False,
        description="Получить и расшифровать запись ключ-значение из профиля пользователя (key).",
    )
    dispatcher.register(
        "profile_delete",
        _handle_profile_delete,
        dangerous=False,
        description="Удалить запись ключ-значение из профиля пользователя (key).",
    )
    dispatcher.register(
        "profile_forget",
        _handle_profile_forget,
        dangerous=False,
        description="Явно забыть запомненный факт по ключу (key) (то же самое, что profile_delete, "
        "для голосовой команды «забудь X»).",
    )
    dispatcher.register(
        "profile_list_keys",
        _handle_profile_list_keys,
        dangerous=False,
        description="Показать все ключи, сохранённые в профиле пользователя (значения не расшифровываются).",
    )
    dispatcher.register(
        "profile_save_about_me",
        _handle_profile_save_about_me,
        dangerous=False,
        description="Сохранить свободный текст «о себе» из панели настроек и извлечь из него структурированные факты (text).",
    )
    dispatcher.register(
        "list_communication_styles",
        _handle_list_communication_styles,
        dangerous=False,
        description="Показать доступные стили общения (key, label, prosody_rate) для интерфейса настроек.",
    )
