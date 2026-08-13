from __future__ import annotations

import asyncio
from pathlib import Path

from core.dispatcher import CommandDispatcher
from modules.plugin_agent.plugin_loader import LoadedPlugin, PluginRegistry


class _StubInstance:
    name = "stub_plugin"
    description = "A stub."
    trigger_patterns = ["скажи привет"]

    def execute(self, params: dict) -> dict:  # pragma: no cover - never called
        raise AssertionError("execute() must not run in-process; it belongs in the sandbox")


def test_register_routes_execution_through_the_sandbox(monkeypatch) -> None:
    # The registered handler must call run_in_sandbox with the plugin's file
    # path — never the loaded instance's execute() directly, which is what
    # the pre-sandbox implementation did.
    dispatcher = CommandDispatcher()
    registry = PluginRegistry(dispatcher)

    captured: dict = {}

    async def fake_run_in_sandbox(plugin_path: Path, params: dict) -> dict:
        captured["plugin_path"] = plugin_path
        captured["params"] = params
        return {"message": "from sandbox"}

    monkeypatch.setattr(
        "modules.plugin_agent.sandbox_runner.run_in_sandbox", fake_run_in_sandbox
    )

    loaded = LoadedPlugin(
        name=_StubInstance.name,
        description=_StubInstance.description,
        trigger_patterns=_StubInstance.trigger_patterns,
        instance=_StubInstance(),
        module_name="modules.plugins._loaded.stub",
        file_path=Path("/fake/stub_plugin.py"),
    )
    registry.register(loaded)

    response = asyncio.run(dispatcher.dispatch("stub_plugin", {"a": "1"}))

    assert response.message == "from sandbox"
    assert captured["plugin_path"] == Path("/fake/stub_plugin.py")
    assert captured["params"] == {"a": "1"}
