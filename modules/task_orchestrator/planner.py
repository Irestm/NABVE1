from __future__ import annotations

import json
import re
from typing import Any

from core.ai_adapter_chain import candidate_chain
from core.logger import get_logger
from core.models import CommandDescriptor
from modules.task_orchestrator.domain import PlanStep, TaskPlan

logger = get_logger(__name__)

# A hard cap on how many dispatcher commands one voice instruction can turn
# into — mirrors modules.ui_automation.grounding.MAX_STEPS's reasoning: this
# grounds a short spoken composite request, not a multi-minute macro.
MAX_STEPS = 5

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


def _build_prompt(goal_text: str, commands: list[CommandDescriptor]) -> str:
    listing = "; ".join(f'"{c.name}": {c.description}' for c in commands)
    return (
        f'Пользователь голосом попросил выполнить составную задачу: "{goal_text}". '
        f"Вот список доступных команд системы и что каждая из них делает: {listing}. "
        "Разбей задачу на последовательность из одной или нескольких этих команд, в порядке "
        "выполнения — используй ТОЛЬКО имена команд из списка выше, ничего не придумывай. Для "
        "каждого шага укажи имя команды (command) и её параметры (params, объект, может быть "
        "пустым — используй те же ключи параметров, что названы в описании команды). Если задачу "
        "нельзя выполнить доступными командами — верни пустой список шагов. Ответь ТОЛЬКО "
        'JSON-объектом без пояснений, строго в формате {"steps": [{"command": "<имя>", '
        '"params": {}}]}.'
    )


def _parse_step(raw_step: Any, valid_commands: set[str]) -> PlanStep | None:
    if not isinstance(raw_step, dict):
        return None
    command = raw_step.get("command")
    if not isinstance(command, str) or command not in valid_commands:
        return None

    raw_params = raw_step.get("params", {})
    if not isinstance(raw_params, dict):
        return None
    # Every dispatcher handler already parses its params out of strings
    # (see e.g. core/dispatcher.py's _handle_click doing int(x)) — this
    # project's existing convention for every voice/HTTP path, not a new
    # contract introduced here.
    params = {str(key): str(value) for key, value in raw_params.items()}
    return PlanStep(command=command, params=params)


def _parse_plan(raw: str, goal_text: str, valid_commands: set[str]) -> TaskPlan | None:
    match = _JSON_OBJECT_PATTERN.search(raw)
    if not match:
        logger.warning("Task plan response contained no JSON object")
        return None

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("Task plan response was not valid JSON")
        return None

    if not isinstance(parsed, dict):
        return None
    raw_steps = parsed.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps or len(raw_steps) > MAX_STEPS:
        return None

    steps: list[PlanStep] = []
    for raw_step in raw_steps:
        step = _parse_step(raw_step, valid_commands)
        if step is None:
            # Same reasoning as modules.ui_automation.grounding._parse_grounding:
            # any single structurally-invalid or hallucinated-command step
            # rejects the whole plan rather than silently dropping it and
            # running a different, shorter sequence than what gets
            # announced to the user.
            return None
        steps.append(step)

    return TaskPlan(goal_text=goal_text, steps=tuple(steps))


async def plan(goal_text: str, commands: list[CommandDescriptor]) -> TaskPlan | None:
    """Tries to turn a free-text composite instruction into a TaskPlan of
    real, already-registered dispatcher commands. Mirrors
    modules.ui_automation.grounding.ground's shape: a candidate-command
    prompt, JSON-only response, regex-extracted + json.loads +
    graceful-None-on-failure parsing, tried across candidate_chain()'s
    adapters in order. Every proposed command name is validated against
    `commands` (see _parse_step) — a hallucinated command name rejects
    that step, and the whole plan with it, never gets executed. Returns
    None if nothing usable came back from any adapter."""
    if not commands:
        return None

    valid_commands = {c.name for c in commands}
    prompt = _build_prompt(goal_text, commands)
    for adapter in candidate_chain(goal_text):
        try:
            raw = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            logger.warning("Task planning adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue
        plan_result = _parse_plan(raw, goal_text, valid_commands)
        if plan_result:
            return plan_result

    return None
