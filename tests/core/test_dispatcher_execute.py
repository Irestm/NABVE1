from __future__ import annotations

import asyncio

from core.dispatcher import CommandDispatcher
from core.models import GENERIC_FAILED_MESSAGE, CommandStatus


def _dispatcher_with(name: str, handler) -> CommandDispatcher:
    dispatcher = CommandDispatcher()
    dispatcher.register(name, handler, dangerous=False, description="")
    return dispatcher


def test_a_deliberate_valueerror_is_shown_verbatim() -> None:
    async def handler(_params):
        raise ValueError("Не указан путь к папке.")

    dispatcher = _dispatcher_with("do_thing", handler)

    response = asyncio.run(dispatcher.dispatch("do_thing", {}))

    assert response.status == CommandStatus.FAILED
    assert response.message == "Не указан путь к папке."


def test_a_deliberate_runtimeerror_is_shown_verbatim() -> None:
    async def handler(_params):
        raise RuntimeError("Сначала войдите в Quizlet.")

    dispatcher = _dispatcher_with("do_thing", handler)

    response = asyncio.run(dispatcher.dispatch("do_thing", {}))

    assert response.message == "Сначала войдите в Quizlet."


def test_an_unexpected_exception_is_replaced_with_the_generic_russian_fallback() -> None:
    # Simulates a library/OS exception nobody wrote deliberately for the
    # user to see — e.g. a raw ConnectionError from a network call, whose
    # str() would otherwise be English and confusing (and, worse, get
    # spoken aloud by TTS — see core/models.py's GENERIC_FAILED_MESSAGE
    # docstring).
    async def handler(_params):
        raise ConnectionError("Connection refused")

    dispatcher = _dispatcher_with("do_thing", handler)

    response = asyncio.run(dispatcher.dispatch("do_thing", {}))

    assert response.status == CommandStatus.FAILED
    assert response.message == GENERIC_FAILED_MESSAGE
    assert "Connection refused" not in response.message
