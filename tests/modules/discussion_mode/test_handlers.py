from __future__ import annotations

import asyncio

import pytest

from core.dispatcher import CommandDispatcher
from modules.discussion_mode import handlers


class _Loop:
    def __init__(self, ok: bool) -> None:
        self._ok = ok
        self.calls = 0
        self.end_calls = 0

    def request_discussion_mode(self) -> bool:
        self.calls += 1
        return self._ok

    def request_end_discussion(self) -> bool:
        self.end_calls += 1
        return self._ok


def test_register_adds_the_commands() -> None:
    dispatcher = CommandDispatcher()
    handlers.register_commands(dispatcher, _Loop(ok=True))
    names = {c.name for c in dispatcher.list_commands()}
    assert {"discussion_start", "discussion_stop"} <= names


def test_stop_handler_signals_the_voice_loop() -> None:
    dispatcher = CommandDispatcher()
    loop = _Loop(ok=True)
    handlers.register_commands(dispatcher, loop)

    response = asyncio.run(dispatcher.dispatch("discussion_stop", {}))

    assert loop.end_calls == 1
    assert "дискуссию" in response.message


def test_stop_handler_fails_when_discussion_not_active() -> None:
    dispatcher = CommandDispatcher()
    handlers.register_commands(dispatcher, _Loop(ok=False))

    response = asyncio.run(dispatcher.dispatch("discussion_stop", {}))

    assert response.status.value == "failed"
    assert "не активен" in response.message


def test_handler_signals_the_voice_loop() -> None:
    dispatcher = CommandDispatcher()
    loop = _Loop(ok=True)
    handlers.register_commands(dispatcher, loop)

    response = asyncio.run(dispatcher.dispatch("discussion_start", {}))

    assert loop.calls == 1
    assert "дискуссии" in response.message


def test_handler_fails_clearly_when_loop_not_running() -> None:
    dispatcher = CommandDispatcher()
    handlers.register_commands(dispatcher, _Loop(ok=False))

    response = asyncio.run(dispatcher.dispatch("discussion_start", {}))

    assert response.status.value == "failed"
    assert "не запущен" in response.message
