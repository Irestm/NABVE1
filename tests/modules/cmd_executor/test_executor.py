from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from modules.cmd_executor import executor


def test_run_whitelisted_returns_captured_output(monkeypatch) -> None:
    fake_completed = MagicMock(returncode=0, stdout="fake output\n", stderr="")
    monkeypatch.setattr(executor.subprocess, "run", lambda *a, **k: fake_completed)

    result = executor.run_whitelisted("uptime")

    assert result == {"name": "uptime", "returncode": 0, "stdout": "fake output\n", "stderr": ""}


def test_run_whitelisted_rejects_unknown_command() -> None:
    with pytest.raises(ValueError):
        executor.run_whitelisted("rm -rf /")


def test_run_whitelisted_raises_runtime_error_on_timeout(monkeypatch) -> None:
    def _raise_timeout(argv, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=1.0)

    monkeypatch.setattr(executor.subprocess, "run", _raise_timeout)

    with pytest.raises(RuntimeError, match="timed out"):
        executor.run_whitelisted("uptime", timeout_seconds=1.0)


def test_run_whitelisted_never_uses_shell(monkeypatch) -> None:
    captured = {}

    def _fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["shell"] = kwargs.get("shell")
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(executor.subprocess, "run", _fake_run)

    executor.run_whitelisted("uptime")

    assert captured["shell"] is False
    assert captured["argv"] == ["uptime"]


def test_subprocess_command_executor_adapter_delegates_to_run_whitelisted(monkeypatch) -> None:
    fake_completed = MagicMock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(executor.subprocess, "run", lambda *a, **k: fake_completed)

    result = executor.SubprocessCommandExecutor.run_whitelisted("uptime")

    assert result["name"] == "uptime"
