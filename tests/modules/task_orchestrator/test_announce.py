from __future__ import annotations

from modules.task_orchestrator.announce import describe_plan
from modules.task_orchestrator.domain import PlanStep, TaskPlan


def test_describe_plan_russian() -> None:
    plan = TaskPlan(
        goal_text="открой калькулятор и покажи окна",
        steps=(PlanStep(command="open_app", params={}), PlanStep(command="list_windows", params={})),
    )
    assert describe_plan(plan, "ru") == "Выполняю составную задачу из 2 шагов: открой калькулятор и покажи окна."


def test_describe_plan_falls_back_to_russian_for_unknown_language() -> None:
    plan = TaskPlan(goal_text="x", steps=(PlanStep(command="c", params={}),))
    assert describe_plan(plan, "fr") == "Выполняю составную задачу из 1 шагов: x."
