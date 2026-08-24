from __future__ import annotations

import asyncio

from core.logger import get_logger
from core.os_adapter import get_os_adapter
from modules.os_agent import planner, safety
from modules.os_agent.domain import MAX_STEPS, AgentSession
from modules.ui_automation import service_layer as ui_service_layer
from modules.ui_automation.announce import describe_step
from modules.ui_automation.domain import UIStep

logger = get_logger(__name__)


async def _execute(adapter, step: UIStep) -> None:
    """Runs one free-tier step for real — same coordinate-center convention
    as modules.ui_automation.service_layer.to_command_params, deliberately
    NOT going through core/dispatcher.py's "ui_action" command (that path is
    reserved for the final, confirmed queue — see
    core/voice/pipeline.py::_dispatch_ui_steps)."""
    if step.action == "click":
        assert step.element is not None
        x, y, w, h = step.element.bbox
        await asyncio.to_thread(adapter.click, x + w // 2, y + h // 2, "left")
    elif step.action == "type_text":
        await asyncio.to_thread(adapter.type_text, step.text)
    else:
        await asyncio.to_thread(adapter.press_key, step.key)


async def run_task(task: str) -> AgentSession:
    """The whole autonomous loop for one voice task, run to completion (or
    barge-in cancellation, via the caller's run_cancellable wrapper) inside a
    single core/voice/pipeline.py turn — no further trigger phrase needed
    per step, see the agreed plan. Every free (non-write) step, as long as
    the queue is still empty, executes for real and the next iteration
    re-observes the resulting screen; the first write step queues instead of
    executing, and every step after that queues too, even a nominally free
    one — see modules/os_agent/safety.py's docstring for why re-observing a
    screen that doesn't yet reflect an unapplied earlier write would be
    misleading rather than helpful."""
    session = AgentSession(task=task)
    adapter = get_os_adapter()

    for _ in range(MAX_STEPS):
        try:
            active = await asyncio.to_thread(adapter.get_active_window)
        except Exception:
            logger.exception("os_agent: get_active_window failed")
            session.outcome = "stuck"
            session.summary = "не удалось определить активное окно."
            break
        if active is None:
            session.outcome = "stuck"
            session.summary = "нет активного окна."
            break

        try:
            elements = await ui_service_layer.list_active_elements(active)
        except Exception:
            logger.exception("os_agent: listing UI elements failed")
            session.outcome = "stuck"
            session.summary = "не удалось прочитать интерфейс активного окна."
            break
        if not elements:
            session.outcome = "stuck"
            session.summary = "в активном окне не нашлось элементов для взаимодействия."
            break

        decision = await planner.decide_next(task, active.title, elements, session.journal)
        if decision is None:
            session.outcome = "throttled" if not planner.has_available_adapter() else "stuck"
            if session.outcome == "stuck":
                session.summary = "не смог понять, что делать дальше."
            break

        if decision.kind == "done":
            session.outcome = "done"
            session.summary = decision.reason or "Готово."
            break
        if decision.kind == "stuck":
            session.outcome = "stuck"
            session.summary = decision.reason or "не смог продолжить."
            break

        step = decision.step
        assert step is not None
        description = describe_step(step, "ru")
        if not session.pending and not safety.is_write_action(step):
            try:
                await _execute(adapter, step)
            except Exception:
                logger.exception("os_agent: executing free-tier step failed")
                session.outcome = "stuck"
                session.summary = "не получилось выполнить действие на экране."
                break
            session.journal.append(f"Выполнено: {description}")
        else:
            session.pending.append(step)
            reason_suffix = f" ({decision.reason})" if decision.reason else ""
            session.journal.append(f"Запланировано: {description}{reason_suffix}")
    else:
        session.outcome = "limit"

    return session
