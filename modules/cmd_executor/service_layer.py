from __future__ import annotations

from typing import Any

from modules.cmd_executor.ports import CommandExecutorPort


def run_command(executor: CommandExecutorPort, name: str | None) -> dict[str, Any]:
    if not name:
        raise ValueError("Не указано имя команды.")
    return executor.run_whitelisted(name)
