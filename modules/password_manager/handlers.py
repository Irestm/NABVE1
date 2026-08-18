from __future__ import annotations

import asyncio
from typing import Any

from core.dispatcher import CommandDispatcher
from modules.password_manager import service_layer
from modules.password_manager.manager import KeyringCredentialStore
from modules.password_manager.ports import CredentialStorePort

_store: CredentialStorePort = KeyringCredentialStore()


async def _handle_password_store(params: dict[str, Any]) -> dict[str, Any]:
    service, username = params.get("service"), params.get("username")
    await asyncio.to_thread(service_layer.store, _store, service, username, params.get("password"))
    return {"service": service, "username": username, "stored": True}


async def _handle_password_get(params: dict[str, Any]) -> dict[str, Any]:
    service, username = params.get("service"), params.get("username")
    password = await asyncio.to_thread(service_layer.get, _store, service, username)
    return {"service": service, "username": username, "password": password}


async def _handle_password_delete(params: dict[str, Any]) -> dict[str, Any]:
    service, username = params.get("service"), params.get("username")
    deleted = await asyncio.to_thread(service_layer.delete, _store, service, username)
    return {"service": service, "username": username, "deleted": deleted}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "password_store",
        _handle_password_store,
        dangerous=True,
        description="Сохранить пароль (service, username, password) в системном хранилище ключей.",
    )
    dispatcher.register(
        "password_get",
        _handle_password_get,
        dangerous=True,
        description="Получить сохранённый пароль (service, username) из системного хранилища ключей.",
    )
    dispatcher.register(
        "password_delete",
        _handle_password_delete,
        dangerous=True,
        description="Удалить сохранённый пароль (service, username) из системного хранилища ключей.",
    )
