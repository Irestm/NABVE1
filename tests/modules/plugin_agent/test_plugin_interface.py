from __future__ import annotations

from modules.plugin_agent.plugin_interface import validate_plugin


class _ValidPlugin:
    name = "plugin_greet"
    description = "Greets the user"
    trigger_patterns = ["привет"]

    def execute(self, params: dict) -> dict:
        return {}


def test_validate_plugin_accepts_a_fully_conforming_candidate() -> None:
    assert validate_plugin(_ValidPlugin()) == []


def test_validate_plugin_reports_all_missing_attributes() -> None:
    class _Empty:
        pass

    errors = validate_plugin(_Empty())

    assert "Missing required attribute 'name'" in errors
    assert "Missing required attribute 'description'" in errors
    assert "Missing required attribute 'trigger_patterns'" in errors
    assert "Missing required attribute 'execute'" in errors


def test_validate_plugin_rejects_non_string_name() -> None:
    class _BadName(_ValidPlugin):
        name = 123

    assert "'name' must be a string" in validate_plugin(_BadName())


def test_validate_plugin_rejects_empty_name() -> None:
    class _EmptyName(_ValidPlugin):
        name = ""

    assert "'name' must be non-empty" in validate_plugin(_EmptyName())


def test_validate_plugin_rejects_non_string_description() -> None:
    class _BadDescription(_ValidPlugin):
        description = 123

    assert "'description' must be a string" in validate_plugin(_BadDescription())


def test_validate_plugin_rejects_non_list_trigger_patterns() -> None:
    class _BadPatterns(_ValidPlugin):
        trigger_patterns = "привет"

    assert "'trigger_patterns' must be a list of strings" in validate_plugin(_BadPatterns())


def test_validate_plugin_accepts_tuple_trigger_patterns() -> None:
    class _TuplePatterns(_ValidPlugin):
        trigger_patterns = ("привет",)

    assert validate_plugin(_TuplePatterns()) == []


def test_validate_plugin_rejects_non_callable_execute() -> None:
    class _BadExecute(_ValidPlugin):
        execute = "not callable"

    assert "'execute' must be callable" in validate_plugin(_BadExecute())
