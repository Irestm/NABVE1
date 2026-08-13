from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanStep:
    """One step of a TaskPlan: a real, already-registered dispatcher
    command name plus its params — never a free-form action of its own.
    See modules.task_orchestrator.planner.plan, which only ever produces
    steps whose command name is in the dispatcher's actual catalog; a
    proposed step naming anything else is rejected before it ever becomes
    a PlanStep."""

    command: str
    params: dict[str, str]


@dataclass(frozen=True)
class TaskPlan:
    """A short, linear sequence of dispatcher commands the planner
    resolved a free-text composite instruction into — see
    modules.task_orchestrator.planner.plan. No persistence, id, or
    per-step status tracking in this first slice: a plan lives only for
    the duration of one voice turn (see
    core/voice/pipeline.py::_resolve_task_plan), the same lifetime as
    modules.ui_automation.domain.UIStep."""

    goal_text: str
    steps: tuple[PlanStep, ...]
