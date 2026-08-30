from __future__ import annotations

import asyncio

import core.voice.web_pipeline as web_pipeline
from core.dispatcher import CommandDispatcher, build_dispatcher
from core.voice.intent import Command


class _ScheduleSpy:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def schedule(self, uow, command, run_at, original_text, pre_confirmed=False):
        self.calls.append((command.name, run_at, original_text, pre_confirmed))
        return 1


def _patch(monkeypatch, resolved: Command | None) -> _ScheduleSpy:
    spy = _ScheduleSpy()
    monkeypatch.setattr(web_pipeline, "delayed_service_layer", spy)
    monkeypatch.setattr(
        web_pipeline.delayed_resolver, "resolve_command", lambda remainder, lang: resolved
    )
    return spy


def test_delayed_command_is_scheduled_not_dispatched(monkeypatch) -> None:
    dispatched: list[str] = []

    async def open_app(_params):
        dispatched.append("open_app")
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("open_app", open_app, dangerous=False, description="")
    spy = _patch(monkeypatch, Command(name="open_app", params={"target": "браузер"}))

    reply, status, token = asyncio.run(
        web_pipeline._resolve_and_dispatch(dispatcher, "открой браузер через 10 минут", "ru", "ru")
    )

    assert dispatched == []
    assert len(spy.calls) == 1
    assert spy.calls[0][0] == "open_app"
    assert "через 10 мин" in reply
    assert status is None and token is None


def test_delayed_command_that_cannot_be_resolved_is_reported(monkeypatch) -> None:
    dispatcher = CommandDispatcher()
    spy = _patch(monkeypatch, None)

    reply, status, token = asyncio.run(
        web_pipeline._resolve_and_dispatch(dispatcher, "побеседуй о жизни через 10 минут", "ru", "ru")
    )

    assert spy.calls == []
    assert "не понял" in reply.lower()


def test_dangerous_delayed_command_is_refused_on_the_stateless_endpoint(monkeypatch) -> None:
    dispatcher = build_dispatcher()
    spy = _patch(monkeypatch, Command(name="shutdown", params={}))

    reply, status, token = asyncio.run(
        web_pipeline._resolve_and_dispatch(dispatcher, "выключи компьютер через час", "ru", "ru")
    )

    assert spy.calls == []
    assert "подтверждени" in reply.lower()
