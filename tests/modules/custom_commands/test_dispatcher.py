from __future__ import annotations

from datetime import datetime

import pytest

from core.dispatcher import CommandDispatcher
from modules.custom_commands import dispatcher as dispatcher_module
from modules.custom_commands.domain import ActionType, CustomCommand


def _command(
    command_id: str, trigger_phrase: str, action_type: ActionType, payload: dict | None = None
) -> CustomCommand:
    return CustomCommand(
        id=command_id,
        trigger_phrase=trigger_phrase,
        action_type=action_type,
        action_payload=payload or {},
        created_at=datetime.now(),
    )


@pytest.fixture(autouse=True)
def _reset_registry():
    dispatcher_module._registry = None
    yield
    dispatcher_module._registry = None


def test_register_one_adds_a_dispatcher_command_for_direct_action_types() -> None:
    dispatcher = CommandDispatcher()
    registry = dispatcher_module.CustomCommandRegistry(dispatcher)
    command = _command("abc123", "открой почту", ActionType.OPEN_LINK, {"url": "https://mail.example"})

    registry.register_one(command)

    names = [c.name for c in dispatcher.list_commands()]
    assert "custom_abc123" in names


def test_register_one_does_not_register_text_instruction_in_the_dispatcher() -> None:
    dispatcher = CommandDispatcher()
    registry = dispatcher_module.CustomCommandRegistry(dispatcher)
    command = _command("txt1", "напиши маме", ActionType.TEXT_INSTRUCTION, {"instruction": "напиши маме привет"})

    registry.register_one(command)

    names = [c.name for c in dispatcher.list_commands()]
    assert "custom_txt1" not in names
    # Still matchable, though - see test_match_finds_text_instruction_commands_too.


def test_register_one_never_marks_a_custom_command_dangerous() -> None:
    # See modules/custom_commands/dispatcher.py's register_one comment: the
    # confirmation gate is re-checked fresh in core/voice/pipeline.py
    # instead, so a toggle flip can't go stale behind a cached dangerous flag.
    dispatcher = CommandDispatcher()
    registry = dispatcher_module.CustomCommandRegistry(dispatcher)
    command = _command("app1", "запусти игру", ActionType.LAUNCH_APP, {"executable_path": "/opt/game/run.sh"})

    registry.register_one(command)

    descriptor = next(c for c in dispatcher.list_commands() if c.name == "custom_app1")
    assert descriptor.dangerous is False


def test_match_exact_and_substring() -> None:
    dispatcher = CommandDispatcher()
    registry = dispatcher_module.CustomCommandRegistry(dispatcher)
    command = _command("abc123", "открой помойку", ActionType.OPEN_LINK, {"url": "https://x"})
    registry.register_one(command)

    assert registry.match("открой помойку") is command
    assert registry.match("так, открой помойку пожалуйста") is command
    assert registry.match("совсем другое") is None


def test_match_prefers_the_longest_matching_trigger_over_insertion_order() -> None:
    dispatcher = CommandDispatcher()
    registry = dispatcher_module.CustomCommandRegistry(dispatcher)
    short_command = _command("short1", "музыка", ActionType.OPEN_LINK, {"url": "https://short"})
    long_command = _command("long1", "включи музыку", ActionType.OPEN_LINK, {"url": "https://long"})
    registry.register_one(short_command)
    registry.register_one(long_command)

    assert registry.match("пожалуйста включи музыку сейчас") is long_command


def test_match_finds_text_instruction_commands_too() -> None:
    dispatcher = CommandDispatcher()
    registry = dispatcher_module.CustomCommandRegistry(dispatcher)
    command = _command("txt1", "напиши маме", ActionType.TEXT_INSTRUCTION, {"instruction": "напиши маме привет"})
    registry.register_one(command)

    assert registry.match("напиши маме") is command


def test_unregister_removes_dispatcher_entry_and_trigger() -> None:
    dispatcher = CommandDispatcher()
    registry = dispatcher_module.CustomCommandRegistry(dispatcher)
    command = _command("abc123", "открой помойку", ActionType.OPEN_LINK, {"url": "https://x"})
    registry.register_one(command)

    registry.unregister("abc123")

    assert "custom_abc123" not in [c.name for c in dispatcher.list_commands()]
    assert registry.match("открой помойку") is None


def test_load_all_drops_commands_deleted_from_storage(monkeypatch) -> None:
    dispatcher = CommandDispatcher()
    registry = dispatcher_module.CustomCommandRegistry(dispatcher)
    kept = _command("keep1", "оставь это", ActionType.OPEN_LINK, {"url": "https://x"})
    removed = _command("gone1", "удали это", ActionType.OPEN_LINK, {"url": "https://y"})
    registry.register_one(kept)
    registry.register_one(removed)

    # Simulate storage now only having `kept` (the other row was deleted).
    monkeypatch.setattr(dispatcher_module, "get_all_commands", lambda uow: [kept])

    registry.load_all()

    names = [c.name for c in dispatcher.list_commands()]
    assert "custom_keep1" in names
    assert "custom_gone1" not in names
    assert registry.match("удали это") is None


def test_register_all_custom_commands_initializes_module_level_registry(monkeypatch) -> None:
    dispatcher = CommandDispatcher()
    monkeypatch.setattr(dispatcher_module, "get_all_commands", lambda uow: [])

    registry = dispatcher_module.register_all_custom_commands(dispatcher)

    assert dispatcher_module.get_registry() is registry
    assert dispatcher_module.match("anything") is None


def test_requires_confirmation_reads_the_profile_fact(monkeypatch) -> None:
    monkeypatch.setattr(dispatcher_module, "get_fact", lambda uow, key: "1")
    assert dispatcher_module.requires_confirmation() is True

    monkeypatch.setattr(dispatcher_module, "get_fact", lambda uow, key: None)
    assert dispatcher_module.requires_confirmation() is False
