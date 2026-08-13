from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Plugin(Protocol):
    name: str
    description: str
    trigger_patterns: list[str]

    def execute(self, params: dict[str, Any]) -> dict[str, Any]: ...


class PluginBase(ABC):
    name: str
    description: str
    trigger_patterns: list[str] = []

    @abstractmethod
    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


REQUIRED_ATTRS = ("name", "description", "trigger_patterns", "execute")


def validate_plugin(candidate: Any) -> list[str]:
    errors: list[str] = []
    for attr in REQUIRED_ATTRS:
        if not hasattr(candidate, attr):
            errors.append(f"Missing required attribute '{attr}'")

    if hasattr(candidate, "name") and not isinstance(candidate.name, str):
        errors.append("'name' must be a string")
    elif hasattr(candidate, "name") and not candidate.name:
        errors.append("'name' must be non-empty")

    if hasattr(candidate, "description") and not isinstance(candidate.description, str):
        errors.append("'description' must be a string")

    if hasattr(candidate, "trigger_patterns") and not isinstance(
        candidate.trigger_patterns, (list, tuple)
    ):
        errors.append("'trigger_patterns' must be a list of strings")

    if hasattr(candidate, "execute") and not callable(candidate.execute):
        errors.append("'execute' must be callable")

    return errors
