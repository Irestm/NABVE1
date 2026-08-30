from __future__ import annotations

from modules.delayed_execution import resolver


def test_resolves_a_rule_based_command() -> None:
    command = resolver.resolve_command("заблокируй экран", "ru")
    assert command is not None and command.name == "lock_screen"


def test_returns_none_when_the_whole_local_chain_declines(monkeypatch) -> None:
    monkeypatch.setattr(resolver, "interpret", lambda text, language: None)
    monkeypatch.setattr(resolver, "match_plugin_command", lambda text: None)
    monkeypatch.setattr(resolver.command_classifier, "match_system_command", lambda text: None)
    assert resolver.resolve_command("что-то невнятное", "ru") is None


def test_rejects_unschedulable_multi_turn_command(monkeypatch) -> None:
    from core.voice.intent import Command

    monkeypatch.setattr(resolver, "interpret", lambda text, language: Command(name="start_board_game", params={}))
    assert resolver.resolve_command("сыграем партию", "ru") is None
