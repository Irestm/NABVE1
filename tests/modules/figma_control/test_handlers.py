from __future__ import annotations

import asyncio

import pytest

import modules.figma_control.handlers as handlers
from core.dispatcher import CommandDispatcher


def test_register_commands_registers_figma_command():
    dispatcher = CommandDispatcher()
    handlers.register_commands(dispatcher)
    names = [c.name for c in dispatcher.list_commands()]
    assert "figma_command" in names


def test_handle_figma_command_returns_process_result(monkeypatch):
    async def fake_process(text: str) -> str:
        assert text == "выдели слой Кнопка"
        return "Слой выделен."

    monkeypatch.setattr(handlers, "process_figma_command", fake_process)

    result = asyncio.run(handlers._handle_figma_command({"text": "выдели слой Кнопка"}))

    assert result == {"message": "Слой выделен."}


def test_handle_figma_command_requires_text():
    with pytest.raises(ValueError):
        asyncio.run(handlers._handle_figma_command({}))
