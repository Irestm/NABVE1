from __future__ import annotations

import sys
import types

import pytest

from core.voice.plugin_match import match_plugin_command


def test_returns_none_when_no_plugin_matches(monkeypatch) -> None:
    fake_module = types.ModuleType("modules.plugin_agent.plugin_loader")
    fake_module.match_command = lambda text: None
    monkeypatch.setitem(sys.modules, "modules.plugin_agent.plugin_loader", fake_module)

    assert match_plugin_command("бла бла бла") is None


def test_returns_command_with_raw_text_param_when_a_plugin_matches(monkeypatch) -> None:
    fake_module = types.ModuleType("modules.plugin_agent.plugin_loader")
    fake_module.match_command = lambda text: "plugin_current_time"
    monkeypatch.setitem(sys.modules, "modules.plugin_agent.plugin_loader", fake_module)

    command = match_plugin_command("сколько время")

    assert command is not None
    assert command.name == "plugin_current_time"
    assert command.params == {"raw_text": "сколько время"}


def test_only_the_import_is_guarded_not_the_match_call(monkeypatch) -> None:
    # match_plugin_command's try/except wraps the import of match_command
    # only — a successfully-imported match_command that itself raises is not
    # caught, per the source's own structure.
    fake_module = types.ModuleType("modules.plugin_agent.plugin_loader")

    def _broken(text: str) -> str | None:
        raise RuntimeError("plugin loader exploded")

    fake_module.match_command = _broken
    monkeypatch.setitem(sys.modules, "modules.plugin_agent.plugin_loader", fake_module)

    with pytest.raises(RuntimeError, match="plugin loader exploded"):
        match_plugin_command("что угодно")


def test_degrades_to_no_match_when_plugin_loader_cannot_be_imported(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "modules.plugin_agent.plugin_loader", None)

    assert match_plugin_command("что угодно") is None
