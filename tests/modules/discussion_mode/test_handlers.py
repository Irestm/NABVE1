from __future__ import annotations

import asyncio

import pytest

from core.dispatcher import CommandDispatcher
from modules.discussion_mode import handlers


class _Loop:
    def __init__(self, ok: bool) -> None:
        self._ok = ok
        self.calls = 0

    def request_discussion_mode(self) -> bool:
        self.calls += 1
        return self._ok


def test_register_adds_the_command() -> None:
    dispatcher = CommandDispatcher()
    handlers.register_commands(dispatcher, _Loop(ok=True))
    assert "discussion_start" in {c.name for c in dispatcher.list_commands()}


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
