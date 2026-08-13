from __future__ import annotations

import asyncio

from core.dispatcher import CommandDispatcher
from core.voice import web_pipeline


def test_messaging_reply_is_not_supported_over_the_stateless_endpoint() -> None:
    dispatcher = CommandDispatcher()
    reply_text, status, token = asyncio.run(
        web_pipeline._resolve_and_dispatch(dispatcher, "ответь", "ru", "ru")
    )

    assert status is None
    assert token is None
    assert "голосового ассистента" in reply_text


def test_messaging_snooze_is_not_supported_over_the_stateless_endpoint() -> None:
    dispatcher = CommandDispatcher()
    reply_text, status, token = asyncio.run(
        web_pipeline._resolve_and_dispatch(dispatcher, "отложи на 10 минут", "ru", "ru")
    )

    assert status is None
    assert token is None
    assert "голосового ассистента" in reply_text
