from __future__ import annotations

import asyncio
from typing import Any

from core.dispatcher import CommandDispatcher
from modules.cmd_executor import service_layer
from modules.cmd_executor.executor import SubprocessCommandExecutor
from modules.cmd_executor.ports import CommandExecutorPort

_executor: CommandExecutorPort = SubprocessCommandExecutor()


async def _handle_run_command(params: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(service_layer.run_command, _executor, params.get("name"))


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "run_command",
        _handle_run_command,
        dangerous=True,
        description="Run a pre-approved whitelisted terminal command by symbolic name (name).",
    )
