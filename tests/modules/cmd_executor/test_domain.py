from __future__ import annotations

import pytest

from modules.cmd_executor.domain import WhitelistedCommand


def test_resolve_known_command_returns_its_argv() -> None:
    command = WhitelistedCommand.resolve("uptime")
    assert command.argv == ["uptime"]


def test_resolve_unknown_command_raises() -> None:
    with pytest.raises(ValueError):
        WhitelistedCommand.resolve("rm -rf /")
