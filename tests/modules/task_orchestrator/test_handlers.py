from __future__ import annotations

import asyncio

import modules.task_orchestrator.handlers as handlers
from core.dispatcher import CommandDispatcher
from core.models import CommandStatus


def _build_dispatcher() -> tuple[CommandDispatcher, list[str]]:
    dispatcher = CommandDispatcher()
    calls: list[str] = []

    async def _handle_ok(params: dict) -> dict:
        calls.append(f"ok:{params}")
        return {"message": "done"}

    async def _handle_dangerous(params: dict) -> dict:
        calls.append(f"dangerous:{params}")
        return {"message": "dangerous done"}

    async def _handle_fail(_params: dict) -> dict:
        raise RuntimeError("boom")

    dispatcher.register("step_ok", _handle_ok, dangerous=False, description="")
    dispatcher.register("step_dangerous", _handle_dangerous, dangerous=True, description="")
    dispatcher.register("step_fail", _handle_fail, dangerous=False, description="")
    handlers.register_commands(dispatcher)
    return dispatcher, calls


async def _dispatch_and_confirm(dispatcher: CommandDispatcher, params: dict):
    # run_task_plan is itself dangerous=True, so a direct dispatch() call
    # returns CONFIRMATION_REQUIRED — confirm it explicitly, mirroring what
    # core/voice/pipeline.py's _resolve_task_plan does right after speaking
    # the plan (see tests/core/voice/test_pipeline_task_plan.py).
    result = await dispatcher.dispatch("run_task_plan", params)
    assert result.status == CommandStatus.CONFIRMATION_REQUIRED
    return await dispatcher.confirm(result.token, True)


def test_executes_steps_in_order() -> None:
    dispatcher, calls = _build_dispatcher()
    params = {
        "steps": [
            {"command": "step_ok", "params": {"a": "1"}},
            {"command": "step_ok", "params": {"b": "2"}},
        ],
        "announcement": "Делаю два шага.",
    }

    result = asyncio.run(_dispatch_and_confirm(dispatcher, params))

    assert result.status == CommandStatus.EXECUTED
    assert calls == ["ok:{'a': '1'}", "ok:{'b': '2'}"]


def test_auto_confirms_dangerous_step_without_asking_again() -> None:
    dispatcher, calls = _build_dispatcher()
    params = {"steps": [{"command": "step_dangerous", "params": {}}]}

    result = asyncio.run(_dispatch_and_confirm(dispatcher, params))

    assert result.status == CommandStatus.EXECUTED
    assert calls == ["dangerous:{}"]


def test_stops_at_first_failing_step() -> None:
    dispatcher, calls = _build_dispatcher()
    params = {
        "steps": [
            {"command": "step_fail", "params": {}},
            {"command": "step_ok", "params": {}},
        ]
    }

    result = asyncio.run(_dispatch_and_confirm(dispatcher, params))

    # run_task_plan's own handler never raised, so it still reports
    # EXECUTED at the top level — the failure is carried in the message,
    # same convention as modules/ui_automation's handler.
    assert result.status == CommandStatus.EXECUTED
    assert "Не всё выполнилось" in result.message
    assert calls == []  # step_ok never ran


def test_missing_steps_raises_and_reports_failed() -> None:
    dispatcher, _ = _build_dispatcher()

    result = asyncio.run(_dispatch_and_confirm(dispatcher, {}))

    assert result.status == CommandStatus.FAILED


def test_registers_run_task_plan_as_dangerous() -> None:
    dispatcher, _ = _build_dispatcher()
    descriptor = next(d for d in dispatcher.list_commands() if d.name == "run_task_plan")
    assert descriptor.dangerous is True
