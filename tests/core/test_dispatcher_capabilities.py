from __future__ import annotations

import asyncio

from core.dispatcher import build_dispatcher
from core.models import CommandStatus


def test_list_capabilities_defaults_to_russian() -> None:
    dispatcher = build_dispatcher()
    response = asyncio.run(dispatcher.dispatch("list_capabilities", {}))
    assert response.status == CommandStatus.EXECUTED
    assert "открой" in response.message.lower()


def test_list_capabilities_respects_language_param() -> None:
    dispatcher = build_dispatcher()
    response = asyncio.run(dispatcher.dispatch("list_capabilities", {"language": "en"}))
    assert "open" in response.message.lower()


def test_list_capabilities_falls_back_to_russian_for_unknown_language() -> None:
    dispatcher = build_dispatcher()
    response = asyncio.run(dispatcher.dispatch("list_capabilities", {"language": "fr"}))
    assert "открой" in response.message.lower()


def test_list_capabilities_is_registered_and_not_dangerous() -> None:
    dispatcher = build_dispatcher()
    descriptors = {d.name: d for d in dispatcher.list_commands()}
    assert "list_capabilities" in descriptors
    assert descriptors["list_capabilities"].dangerous is False
