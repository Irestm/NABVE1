from __future__ import annotations

import subprocess
from typing import Any

from core.logger import get_logger
from modules.cmd_executor.domain import WhitelistedCommand

logger = get_logger(__name__)


def run_whitelisted(name: str, timeout_seconds: float = 10.0) -> dict[str, Any]:
    argv = WhitelistedCommand.resolve(name).argv
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error("Whitelisted command '%s' (argv=%s) timed out", name, argv)
        raise RuntimeError(f"Command '{name}' timed out after {timeout_seconds}s") from exc

    logger.info(
        "Executed whitelisted command '%s' argv=%s returncode=%s",
        name,
        argv,
        completed.returncode,
    )
    return {
        "name": name,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


class SubprocessCommandExecutor:
    """Adapter satisfying modules.cmd_executor.ports.CommandExecutorPort."""

    run_whitelisted = staticmethod(run_whitelisted)
