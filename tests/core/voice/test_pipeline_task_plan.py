from __future__ import annotations

import asyncio

import core.voice.pipeline as pipeline_module
from core.dispatcher import CommandDispatcher
from core.voice.intent import Command
from core.voice.pipeline import VoiceAssistantLoop
from modules.task_orchestrator.domain import PlanStep, TaskPlan


def _make_loop(dispatcher: CommandDispatcher | None = None) -> VoiceAssistantLoop:
    return VoiceAssistantLoop(dispatcher or CommandDispatcher())


def _run_coro_directly(coro, barge_in, language):
    # Stands in for core.voice.interruption.run_cancellable in tests — see
    # tests/core/voice/test_pipeline_ui_automation.py's identical helper.
    return asyncio.run(coro)


def _patch_no_barge_in(monkeypatch) -> None:
    monkeypatch.setattr(pipeline_module, "run_cancellable", _run_coro_directly)


_PLAN = TaskPlan(
    goal_text="открой калькулятор и покажи окна",
    steps=(PlanStep(command="open_app", params={"target": "calculator"}), PlanStep(command="list_windows", params={})),
)


def test_resolve_task_plan_dispatches_and_confirms_after_announcing(monkeypatch) -> None:
    # run_task_plan is registered dangerous=True (it can dispatch any other
    # command, including other dangerous ones — see
    # modules/task_orchestrator/handlers.py), so the resolver must
    # dispatch() -> get CONFIRMATION_REQUIRED -> confirm() itself, exactly
    # like _resolve_ui_action already does for the same reason.
    _patch_no_barge_in(monkeypatch)

    async def fake_build_plan(raw_text, dispatcher):
        assert raw_text == "открой калькулятор и покажи окна"
        return _PLAN

    monkeypatch.setattr(pipeline_module.task_orchestrator_service_layer, "build_plan", fake_build_plan)
    monkeypatch.setattr(
        pipeline_module.task_orchestrator_announce, "describe_plan", lambda plan, lang: "Выполняю два шага."
    )

    executed: list[dict] = []

    async def handler(params: dict) -> dict:
        executed.append(params)
        return {"message": "Готово, всё выполнено."}

    dispatcher = CommandDispatcher()
    dispatcher.register("run_task_plan", handler, dangerous=True, description="")
    loop = _make_loop(dispatcher)

    spoken: list[str] = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)

    command = Command(name="run_task_plan", params={"raw_text": "открой калькулятор и покажи окна"})

    result, interrupted = loop._resolve_task_plan(command, tts=None, response_language="ru")

    assert result is None
    assert interrupted is False
    assert spoken == ["Выполняю два шага.", "Готово, всё выполнено."]
    assert executed == [
        {
            "steps": [
                {"command": "open_app", "params": {"target": "calculator"}},
                {"command": "list_windows", "params": {}},
            ],
            "announcement": "Выполняю два шага.",
        }
    ]


def test_resolve_task_plan_does_not_dispatch_when_announcement_is_interrupted(monkeypatch) -> None:
    _patch_no_barge_in(monkeypatch)

    async def fake_build_plan(raw_text, dispatcher):
        return _PLAN

    monkeypatch.setattr(pipeline_module.task_orchestrator_service_layer, "build_plan", fake_build_plan)
    monkeypatch.setattr(
        pipeline_module.task_orchestrator_announce, "describe_plan", lambda plan, lang: "Выполняю два шага."
    )

    executed: list[dict] = []

    async def handler(params: dict) -> dict:
        executed.append(params)
        return {"message": "Готово."}

    dispatcher = CommandDispatcher()
    dispatcher.register("run_task_plan", handler, dangerous=True, description="")
    loop = _make_loop(dispatcher)

    # Barge-in cuts off the announcement itself.
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: True)

    command = Command(name="run_task_plan", params={"raw_text": "открой калькулятор и покажи окна"})

    result, interrupted = loop._resolve_task_plan(command, tts=None, response_language="ru")

    assert result is None
    assert interrupted is True
    assert executed == []  # never dispatched — the user interrupted before hearing the plan


def test_resolve_task_plan_gives_up_when_planning_finds_nothing(monkeypatch) -> None:
    _patch_no_barge_in(monkeypatch)

    async def fake_build_plan(raw_text, dispatcher):
        return None

    monkeypatch.setattr(pipeline_module.task_orchestrator_service_layer, "build_plan", fake_build_plan)

    dispatcher = CommandDispatcher()
    loop = _make_loop(dispatcher)
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)

    command = Command(name="run_task_plan", params={"raw_text": "бессвязная фраза"})

    result, interrupted = loop._resolve_task_plan(command, tts=None, response_language="ru")

    assert result is None
    assert interrupted is False


def test_resolve_task_plan_gives_up_when_plan_has_no_steps(monkeypatch) -> None:
    _patch_no_barge_in(monkeypatch)

    async def fake_build_plan(raw_text, dispatcher):
        return TaskPlan(goal_text=raw_text, steps=())

    monkeypatch.setattr(pipeline_module.task_orchestrator_service_layer, "build_plan", fake_build_plan)

    dispatcher = CommandDispatcher()
    loop = _make_loop(dispatcher)
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)

    command = Command(name="run_task_plan", params={"raw_text": "невыполнимая задача"})

    result, interrupted = loop._resolve_task_plan(command, tts=None, response_language="ru")

    assert result is None
    assert interrupted is False
