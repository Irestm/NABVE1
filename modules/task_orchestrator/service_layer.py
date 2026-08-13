from __future__ import annotations

from core.dispatcher import CommandDispatcher
from modules.task_orchestrator import planner
from modules.task_orchestrator.domain import TaskPlan

# The orchestrator's own command must never be offered to the planner as a
# candidate step — a composite instruction "planning" a step that re-runs
# run_task_plan would be unbounded recursion through the dispatcher, which
# modules.task_orchestrator.handlers never meant to allow. Kept here (not
# just in handlers.py) since this is also the name build_plan below filters
# out of the candidate list.
ORCHESTRATOR_COMMAND_NAME = "run_task_plan"


async def build_plan(goal_text: str, dispatcher: CommandDispatcher) -> TaskPlan | None:
    """Asks the planner to turn a free-text composite instruction into a
    TaskPlan of real dispatcher commands — see
    modules.task_orchestrator.planner.plan for the actual model call and
    per-step validation. Called from
    core/voice/pipeline.py::_resolve_task_plan before anything is spoken
    or executed."""
    commands = [c for c in dispatcher.list_commands() if c.name != ORCHESTRATOR_COMMAND_NAME]
    return await planner.plan(goal_text, commands)
