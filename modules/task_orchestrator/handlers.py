from __future__ import annotations

from typing import Any

from core.dispatcher import CommandDispatcher
from core.logger import get_logger
from core.models import CommandStatus

logger = get_logger(__name__)


def register_commands(dispatcher: CommandDispatcher) -> None:
    async def _handle_run_task_plan(params: dict[str, Any]) -> dict[str, Any]:
        """Executes an already-built, already-announced TaskPlan step by
        step through this same dispatcher — a "dumb executor" in the same
        sense as modules.ui_automation.handlers._handle_ui_action: the
        actual planning (modules.task_orchestrator.service_layer.build_plan)
        and the spoken announcement both already happened earlier, in
        core/voice/pipeline.py's pre-dispatch hook (_resolve_task_plan) —
        by the time this runs, `steps` is just a list of plain-primitive
        {command, params} dicts.

        A step that's itself dangerous=True (e.g. a plan that includes
        "shutdown") is auto-confirmed rather than asking a second time:
        the whole plan was already spoken aloud and confirmed once, up
        front — see _resolve_task_plan's docstring, same reasoning
        _resolve_ui_action already established for a single dangerous
        action.

        Stops at the first step that doesn't reach EXECUTED rather than
        continuing blindly through the rest of the plan — a later step
        often depends on an earlier one having actually succeeded (e.g.
        "open X and then click Y" makes no sense to continue if X never
        opened)."""
        steps = params.get("steps")
        if not steps or not isinstance(steps, list):
            raise ValueError("Missing required parameter 'steps'")

        results: list[dict[str, Any]] = []
        for step in steps:
            command = step.get("command")
            step_params = step.get("params") or {}

            response = await dispatcher.dispatch(command, step_params)
            if response.status == CommandStatus.CONFIRMATION_REQUIRED and response.token:
                response = await dispatcher.confirm(response.token, True)

            results.append(
                {"command": command, "status": response.status.value, "message": response.message}
            )
            if response.status != CommandStatus.EXECUTED:
                logger.warning(
                    "Task plan step '%s' did not execute (status=%s); stopping plan",
                    command,
                    response.status,
                )
                return {"steps": results, "message": f"Не всё выполнилось: {response.message}"}

        return {"steps": results, "message": params.get("announcement") or "Готово, всё выполнено."}

    dispatcher.register(
        "run_task_plan",
        _handle_run_task_plan,
        # dangerous=True: this can dispatch ANY registered command,
        # including other dangerous=True ones (auto-confirmed, see the
        # handler's own docstring above) — strictly more powerful than any
        # single command, so it must be gated at least as tightly as the
        # most dangerous thing it could end up running.
        # core/voice/pipeline.py's own resolver (_resolve_task_plan)
        # already speaks the full plan aloud before dispatching and
        # auto-confirms right after, mirroring modules/ui_automation's
        # ui_action — see that command's own dangerous=True comment for
        # the identical raw-API-bypass reasoning (a raw /api/command call
        # can't supply the already-resolved `steps` shape this handler
        # requires without having gone through the announcement step).
        dangerous=True,
        description=(
            "Break a composite, multi-step voice instruction (raw_text) into a sequence of this "
            "system's other commands and run them in order — e.g. 'открой калькулятор и покажи "
            "список окон'. Use this only when the request clearly names two or more distinct "
            "actions to perform one after another; a single action should use its own specific "
            "command instead."
        ),
    )
