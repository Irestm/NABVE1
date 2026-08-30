from __future__ import annotations

import asyncio

import core.voice.web_pipeline as web_pipeline
from core.dispatcher import CommandDispatcher
from core.voice.intent import Command


def _patch_resolution(monkeypatch, mapping: dict[str, Command | None]) -> None:
    monkeypatch.setattr(web_pipeline, "interpret", lambda text, language: mapping.get(text.strip()))
    monkeypatch.setattr(web_pipeline.command_classifier, "match_system_command", lambda text: None)

    async def _no_free_text(*_args, **_kwargs):
        return None, None

    monkeypatch.setattr(web_pipeline.ai_router, "resolve_free_text", _no_free_text)


def test_chained_utterance_dispatches_every_sub_command_in_order(monkeypatch) -> None:
    order: list[str] = []

    async def mute(_params):
        order.append("mute")
        return {}

    async def minimize(_params):
        order.append("minimize")
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("mute", mute, dangerous=False, description="")
    dispatcher.register("minimize_window", minimize, dangerous=False, description="")
    _patch_resolution(
        monkeypatch,
        {
            "выключи звук и сверни окно": None,
            "выключи звук": Command(name="mute", params={}),
            "сверни окно": Command(name="minimize_window", params={}),
        },
    )

    reply, status, token = asyncio.run(
        web_pipeline._resolve_and_dispatch(dispatcher, "выключи звук и сверни окно", "ru", "ru")
    )

    assert order == ["mute", "minimize"]
    assert status is None and token is None


def test_unresolved_sub_command_is_named_in_the_combined_reply(monkeypatch) -> None:
    executed: list[str] = []

    async def mute(_params):
        executed.append("mute")
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("mute", mute, dangerous=False, description="")
    _patch_resolution(
        monkeypatch,
        {
            "выключи звук и станцуй лезгинку": None,
            "выключи звук": Command(name="mute", params={}),
            "станцуй лезгинку": None,
        },
    )

    reply, status, token = asyncio.run(
        web_pipeline._resolve_and_dispatch(dispatcher, "выключи звук и станцуй лезгинку", "ru", "ru")
    )

    assert executed == ["mute"]
    assert "не понял" in reply.lower()
    assert "станцуй лезгинку" in reply


def test_dangerous_sub_command_is_deferred_not_executed(monkeypatch) -> None:
    executed: list[str] = []

    async def minimize(_params):
        executed.append("minimize")
        return {}

    async def shutdown(_params):
        executed.append("shutdown")
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("minimize_window", minimize, dangerous=False, description="")
    dispatcher.register("shutdown", shutdown, dangerous=True, description="")
    _patch_resolution(
        monkeypatch,
        {
            "сверни окно и выключи компьютер": None,
            "сверни окно": Command(name="minimize_window", params={}),
            "выключи компьютер": Command(name="shutdown", params={}),
        },
    )

    reply, status, token = asyncio.run(
        web_pipeline._resolve_and_dispatch(dispatcher, "сверни окно и выключи компьютер", "ru", "ru")
    )

    assert executed == ["minimize"]
    assert "подтверждени" in reply.lower()
    assert "выключи компьютер" in reply
    assert dispatcher._pending == {}
