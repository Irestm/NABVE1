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
        raise ValueError("Missing required parameter 'key'")
    if value is None:
        raise ValueError("Missing required parameter 'value'")
    await asyncio.to_thread(service_layer.set_fact, ProfileUnitOfWork(), key, value)
    return {"key": key, "stored": True}


async def _handle_profile_get(params: dict[str, Any]) -> dict[str, Any]:
    key = params.get("key")
    if not key:
        raise ValueError("Missing required parameter 'key'")
    value = await asyncio.to_thread(service_layer.get_fact, ProfileUnitOfWork(), key)
    return {"key": key, "value": value}


async def _handle_profile_delete(params: dict[str, Any]) -> dict[str, Any]:
    key = params.get("key")
    if not key:
        raise ValueError("Missing required parameter 'key'")
    deleted = await asyncio.to_thread(service_layer.delete_fact, ProfileUnitOfWork(), key)
    return {"key": key, "deleted": deleted}


async def _handle_profile_forget(params: dict[str, Any]) -> dict[str, Any]:
    key = params.get("key")
    if not key:
        raise ValueError("Missing required parameter 'key'")
    forgotten = await asyncio.to_thread(service_layer.forget, ProfileUnitOfWork(), key)
    return {"key": key, "forgotten": forgotten}


async def _handle_profile_list_keys(_params: dict[str, Any]) -> dict[str, Any]:
    keys = await asyncio.to_thread(service_layer.list_keys, ProfileUnitOfWork())
    return {"keys": keys}


async def _handle_profile_save_about_me(params: dict[str, Any]) -> dict[str, Any]:
    text = params.get("text")
    if not text:
        raise ValueError("Missing required parameter 'text'")
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
        description="Store an encrypted key-value entry in the user profile (key, value).",
    )
    dispatcher.register(
        "profile_get",
        _handle_profile_get,
        dangerous=False,
        description="Retrieve and decrypt a key-value entry from the user profile (key).",
    )
    dispatcher.register(
        "profile_delete",
        _handle_profile_delete,
        dangerous=False,
        description="Delete a key-value entry from the user profile (key).",
    )
    dispatcher.register(
        "profile_forget",
        _handle_profile_forget,
        dangerous=False,
        description="Explicitly forget a remembered fact by key (key) (same effect as profile_delete, "
        "phrased for the 'forget X' voice command).",
    )
    dispatcher.register(
        "profile_list_keys",
        _handle_profile_list_keys,
        dangerous=False,
        description="List all keys stored in the user profile (values not decrypted).",
    )
    dispatcher.register(
        "profile_save_about_me",
        _handle_profile_save_about_me,
        dangerous=False,
        description="Store the settings panel's free-text 'about me' field and extract structured facts from it (text).",
    )
    dispatcher.register(
        "list_communication_styles",
        _handle_list_communication_styles,
        dangerous=False,
        description="List available communication styles (key, label, prosody_rate) for the settings UI.",
    )
