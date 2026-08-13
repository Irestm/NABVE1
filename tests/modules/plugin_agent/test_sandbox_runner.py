from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

import pytest

import modules.plugin_agent.sandbox_runner as sandbox_runner
from modules.plugin_agent.sandbox_runner import PluginSandboxError, run_in_sandbox

# Real subprocesses (see run_in_sandbox) — slower than a typical unit test,
# but this is exactly the boundary the feature exists to enforce, so faking
# it away would test nothing real.


def _write_plugin(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "plugin.py"
    path.write_text(source, encoding="utf-8")
    return path


def test_runs_plugin_and_returns_result(tmp_path: Path) -> None:
    path = _write_plugin(
        tmp_path,
        """
class P:
    name = "p"
    description = "d"
    trigger_patterns = []

    def execute(self, params):
        return {"got": params.get("x"), "message": "done"}

plugin = P()
""",
    )

    result = asyncio.run(run_in_sandbox(path, {"x": "hello"}))

    assert result == {"got": "hello", "message": "done"}


def test_secret_env_vars_are_not_visible_to_the_plugin(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ASSISTANT_TEST_SECRET", "super-secret-value")
    path = _write_plugin(
        tmp_path,
        """
import os

class P:
    name = "p"
    description = "d"
    trigger_patterns = []

    def execute(self, params):
        return {"secret": os.environ.get("ASSISTANT_TEST_SECRET")}

plugin = P()
""",
    )

    result = asyncio.run(run_in_sandbox(path, {}))

    assert result == {"secret": None}


def test_forbidden_import_is_rejected_with_a_specific_message(tmp_path: Path) -> None:
    path = _write_plugin(
        tmp_path,
        """
import keyring

class P:
    name = "p"
    description = "d"
    trigger_patterns = []

    def execute(self, params):
        return {}

plugin = P()
""",
    )

    with pytest.raises(PluginSandboxError, match="forbidden import 'keyring'"):
        asyncio.run(run_in_sandbox(path, {}))


def test_execute_exception_is_reported_with_its_own_message(tmp_path: Path) -> None:
    path = _write_plugin(
        tmp_path,
        """
class P:
    name = "p"
    description = "d"
    trigger_patterns = []

    def execute(self, params):
        raise ValueError("oops from plugin")

plugin = P()
""",
    )

    with pytest.raises(PluginSandboxError, match="oops from plugin"):
        asyncio.run(run_in_sandbox(path, {}))


def test_missing_plugin_instance_is_reported(tmp_path: Path) -> None:
    path = _write_plugin(tmp_path, "x = 1\n")

    with pytest.raises(PluginSandboxError):
        asyncio.run(run_in_sandbox(path, {}))


def test_timeout_kills_a_hanging_plugin(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sandbox_runner, "_TIMEOUT_SECONDS", 1.0)
    path = _write_plugin(
        tmp_path,
        """
import time

class P:
    name = "p"
    description = "d"
    trigger_patterns = []

    def execute(self, params):
        time.sleep(60)
        return {}

plugin = P()
""",
    )

    start = time.monotonic()
    with pytest.raises(PluginSandboxError, match="timed out"):
        asyncio.run(run_in_sandbox(path, {}))
    assert time.monotonic() - start < 10  # well under the plugin's own 60s sleep
