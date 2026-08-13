from __future__ import annotations

import asyncio

import modules.task_orchestrator.service_layer as service_layer
from core.dispatcher import CommandDispatcher
from modules.task_orchestrator.domain import TaskPlan


async def _noop(_params: dict) -> dict:
    return {}


def test_build_plan_excludes_orchestrator_command_from_candidates(monkeypatch) -> None:
    dispatcher = CommandDispatcher()
    dispatcher.register("open_app", _noop, description="Open an app.")
    dispatcher.register("run_task_plan", _noop, dangerous=True, description="Composite.")

    captured: dict = {}

    async def fake_plan(goal_text, commands):
        captured["commands"] = commands
        return None

    monkeypatch.setattr(service_layer.planner, "plan", fake_plan)

    asyncio.run(service_layer.build_plan("сделай что-то", dispatcher))

    names = [c.name for c in captured["commands"]]
    assert "run_task_plan" not in names
    assert "open_app" in names


def test_build_plan_returns_planner_result(monkeypatch) -> None:
    dispatcher = CommandDispatcher()
    dispatcher.register("open_app", _noop, description="Open an app.")
    fake_plan_result = TaskPlan(goal_text="x", steps=())

    async def fake_plan(goal_text, commands):
        return fake_plan_result

    monkeypatch.setattr(service_layer.planner, "plan", fake_plan)

    result = asyncio.run(service_layer.build_plan("x", dispatcher))

    assert result is fake_plan_result
