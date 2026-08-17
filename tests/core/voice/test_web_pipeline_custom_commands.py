from __future__ import annotations

import asyncio
from datetime import datetime

from core.dispatcher import CommandDispatcher
from core.voice import web_pipeline
from modules.custom_commands import dispatcher as custom_commands_registry
from modules.custom_commands.domain import ActionType, CustomCommand


def _command(command_id: str, trigger_phrase: str, action_type: ActionType, payload: dict | None = None) -> CustomCommand:
    return CustomCommand(
        id=command_id,
        trigger_phrase=trigger_phrase,
        action_type=action_type,
        action_payload=payload or {},
        created_at=datetime.now(),
    )


def test_matched_open_link_custom_command_dispatches_over_the_stateless_endpoint(monkeypatch) -> None:
    command = _command("abc123", "открой почту", ActionType.OPEN_LINK, {"url": "https://mail.example"})
    monkeypatch.setattr(custom_commands_registry, "match", lambda text: command)
    monkeypatch.setattr(custom_commands_registry, "requires_confirmation", lambda: False)

    dispatcher = CommandDispatcher()

    async def _handler(_params: dict) -> dict:
        return {"message": "Открываю почту."}

    dispatcher.register("custom_abc123", _handler, dangerous=False, description="")

    reply_text, status, _token = asyncio.run(
        web_pipeline._resolve_and_dispatch(dispatcher, "открой почту", "ru", "ru")
    )

    assert status == "executed"
    assert "Открываю почту" in reply_text


def test_launch_app_custom_command_needing_confirmation_is_not_supported_over_the_stateless_endpoint(
    monkeypatch,
) -> None:
    command = _command("app1", "запусти игру", ActionType.LAUNCH_APP, {"executable_path": "/opt/game/run.sh"})
    monkeypatch.setattr(custom_commands_registry, "match", lambda text: command)
    monkeypatch.setattr(custom_commands_registry, "requires_confirmation", lambda: True)

    dispatcher = CommandDispatcher()

    reply_text, status, token = asyncio.run(
        web_pipeline._resolve_and_dispatch(dispatcher, "запусти игру", "ru", "ru")
    )

    assert status is None
    assert token is None
    assert "голосового ассистента" in reply_text


def test_launch_app_custom_command_not_needing_confirmation_dispatches_directly(monkeypatch) -> None:
    command = _command("app2", "запусти калькулятор", ActionType.LAUNCH_APP, {"executable_path": "/usr/bin/calc"})
    monkeypatch.setattr(custom_commands_registry, "match", lambda text: command)
    monkeypatch.setattr(custom_commands_registry, "requires_confirmation", lambda: False)

    dispatcher = CommandDispatcher()

    async def _handler(_params: dict) -> dict:
        return {"message": "Запускаю калькулятор."}

    dispatcher.register("custom_app2", _handler, dangerous=False, description="")

    reply_text, status, _token = asyncio.run(
        web_pipeline._resolve_and_dispatch(dispatcher, "запусти калькулятор", "ru", "ru")
    )

    assert status == "executed"
    assert "Запускаю калькулятор" in reply_text


def test_text_instruction_custom_command_substitutes_text_before_interpret(monkeypatch) -> None:
    command = _command("txt1", "погода", ActionType.TEXT_INSTRUCTION, {"instruction": "который час"})
    monkeypatch.setattr(custom_commands_registry, "match", lambda text: command)
    monkeypatch.setattr(custom_commands_registry, "requires_confirmation", lambda: False)

    seen: dict[str, str] = {}

    def _fake_interpret(text: str, _language: str):
        seen["text"] = text
        return None

    async def _fake_resolve_free_text(text: str, _commands: list):
        seen["ai_text"] = text
        return None, "ok"

    monkeypatch.setattr(web_pipeline, "interpret", _fake_interpret)
    monkeypatch.setattr(web_pipeline, "match_plugin_command", lambda text: None)
    monkeypatch.setattr(web_pipeline.command_classifier, "match_system_command", lambda text: None)
    monkeypatch.setattr(web_pipeline.ai_router, "resolve_free_text", _fake_resolve_free_text)

    dispatcher = CommandDispatcher()
    asyncio.run(web_pipeline._resolve_and_dispatch(dispatcher, "погода", "ru", "ru"))

    assert seen["text"] == "который час"


def test_text_instruction_custom_command_needing_confirmation_is_not_supported(monkeypatch) -> None:
    command = _command("txt2", "напиши маме", ActionType.TEXT_INSTRUCTION, {"instruction": "напиши маме привет"})
    monkeypatch.setattr(custom_commands_registry, "match", lambda text: command)
    monkeypatch.setattr(custom_commands_registry, "requires_confirmation", lambda: True)

    def _fake_interpret(_text: str, _language: str):
        raise AssertionError("interpret() must not run when confirmation is required and refused")

    monkeypatch.setattr(web_pipeline, "interpret", _fake_interpret)

    dispatcher = CommandDispatcher()
    reply_text, status, token = asyncio.run(
        web_pipeline._resolve_and_dispatch(dispatcher, "напиши маме", "ru", "ru")
    )

    assert status is None
    assert token is None
    assert "голосового ассистента" in reply_text


def test_no_custom_command_match_falls_through_to_interpret(monkeypatch) -> None:
    monkeypatch.setattr(custom_commands_registry, "match", lambda text: None)

    seen: dict[str, str] = {}

    def _fake_interpret(text: str, _language: str):
        seen["text"] = text
        return None

    async def _fake_resolve_free_text(text: str, _commands: list):
        return None, "ok"

    monkeypatch.setattr(web_pipeline, "interpret", _fake_interpret)
    monkeypatch.setattr(web_pipeline, "match_plugin_command", lambda text: None)
    monkeypatch.setattr(web_pipeline.command_classifier, "match_system_command", lambda text: None)
    monkeypatch.setattr(web_pipeline.ai_router, "resolve_free_text", _fake_resolve_free_text)

    dispatcher = CommandDispatcher()
    asyncio.run(web_pipeline._resolve_and_dispatch(dispatcher, "который час", "ru", "ru"))

    assert seen["text"] == "который час"
