from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CommandExecutorPort(Protocol):
    def run_whitelisted(self, name: str, timeout_seconds: float = 10.0) -> dict[str, Any]: ...
