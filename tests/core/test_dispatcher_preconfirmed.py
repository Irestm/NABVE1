from __future__ import annotations

import asyncio

import pytest

from core.dispatcher import CommandDispatcher, UnknownCommandError
from core.models import CommandStatus


def _dispatcher() -> tuple[CommandDispatcher, list[str]]:
    ran: list[str] = []

    async def boom(_params):
        ran.append("boom")
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("boom", boom, dangerous=True, description="")
    return dispatcher, ran


def test_dispatch_preconfirmed_skips_the_confirmation_gate() -> None:
    dispatcher, ran = _dispatcher()

    response = asyncio.run(dispatcher.dispatch_preconfirmed("boom", {}))

    assert response.status is CommandStatus.EXECUTED
    assert ran == ["boom"]


def test_plain_dispatch_still_gates_the_same_command() -> None:
    dispatcher, ran = _dispatcher()

    response = asyncio.run(dispatcher.dispatch("boom", {}))

    assert response.status is CommandStatus.CONFIRMATION_REQUIRED
    assert ran == []


def test_dispatch_preconfirmed_unknown_command_raises() -> None:
    dispatcher, _ = _dispatcher()
    with pytest.raises(UnknownCommandError):
        asyncio.run(dispatcher.dispatch_preconfirmed("nope", {}))


def test_is_dangerous_reports_registration() -> None:
    dispatcher, _ = _dispatcher()
    assert dispatcher.is_dangerous("boom") is True
    assert dispatcher.is_dangerous("missing") is False
