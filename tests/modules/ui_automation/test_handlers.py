from __future__ import annotations

import asyncio

import pytest

import modules.ui_automation.handlers as handlers
from core.dispatcher import CommandDispatcher


class _RecordingAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def click(self, x: int, y: int, button: str = "left") -> None:
        self.calls.append(("click", x, y, button))

    def type_text(self, text: str) -> None:
        self.calls.append(("type_text", text))

    def press_key(self, key: str) -> None:
        self.calls.append(("press_key", key))


def test_handle_ui_action_executes_steps_in_order(monkeypatch) -> None:
    adapter = _RecordingAdapter()
    monkeypatch.setattr(handlers, "get_os_adapter", lambda: adapter)

    params = {
        "steps": [
            {"action": "click", "x": 10, "y": 20, "button": "left"},
            {"action": "type_text", "text": "привет"},
            {"action": "press_key", "key": "Enter"},
        ],
        "announcement": "Нажимаю кнопку.",
    }

    result = asyncio.run(handlers._handle_ui_action(params))

    assert adapter.calls == [
        ("click", 10, 20, "left"),
        ("type_text", "привет"),
        ("press_key", "Enter"),
    ]
    assert result == {"steps": params["steps"], "message": "Нажимаю кнопку."}


def test_handle_ui_action_missing_steps_raises() -> None:
    with pytest.raises(ValueError):
        asyncio.run(handlers._handle_ui_action({}))


def test_handle_ui_action_unknown_step_action_raises(monkeypatch) -> None:
    monkeypatch.setattr(handlers, "get_os_adapter", lambda: _RecordingAdapter())
    with pytest.raises(ValueError):
        asyncio.run(handlers._handle_ui_action({"steps": [{"action": "scroll"}]}))


def test_handle_ui_action_default_message_when_no_announcement(monkeypatch) -> None:
    adapter = _RecordingAdapter()
    monkeypatch.setattr(handlers, "get_os_adapter", lambda: adapter)

    result = asyncio.run(
        handlers._handle_ui_action({"steps": [{"action": "press_key", "key": "Escape"}]})
    )

    assert result["message"] == "Готово."


def test_register_commands_registers_ui_action() -> None:
    dispatcher = CommandDispatcher()
    handlers.register_commands(dispatcher)
    names = [descriptor.name for descriptor in dispatcher.list_commands()]
    assert "ui_action" in names


def test_register_commands_registers_ui_action_as_dangerous() -> None:
    # A click/type_text/press_key sequence is full remote control of this
    # machine's mouse and keyboard — see core/main.py's POST /api/command,
    # an unauthenticated pass-through listening on the LAN by default.
    # dangerous=False here would let any device on the network drive this
    # machine with zero confirmation.
    dispatcher = CommandDispatcher()
    handlers.register_commands(dispatcher)
    descriptor = next(d for d in dispatcher.list_commands() if d.name == "ui_action")
    assert descriptor.dangerous is True
