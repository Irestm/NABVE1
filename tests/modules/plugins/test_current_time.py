from __future__ import annotations

from modules.plugins.current_time import CurrentTimePlugin, plugin


def test_plugin_module_instance_is_a_current_time_plugin() -> None:
    assert isinstance(plugin, CurrentTimePlugin)
    assert plugin.name == "plugin_current_time"
    assert "который час" in plugin.trigger_patterns


def test_execute_returns_iso_human_and_message_fields() -> None:
    result = CurrentTimePlugin().execute({})

    assert set(result.keys()) == {"iso", "human", "message"}
    assert "Сейчас" in result["message"]
