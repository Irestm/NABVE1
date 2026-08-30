from __future__ import annotations

from datetime import datetime

from core.dispatcher import CommandDispatcher
from core.logger import get_logger
from core.models import CommandStatus
from core.voice.intent import Command
from modules.delayed_execution.domain import DelayedCommand, DelayedCommandStatus
from modules.delayed_execution.uow import DelayedExecutionUnitOfWork

logger = get_logger(__name__)


def schedule(
    uow: DelayedExecutionUnitOfWork,
    command: Command,
    run_at: datetime,
    original_text: str,
    pre_confirmed: bool = False,
) -> int:
    with uow:
        new_id = uow.commands.add(
            DelayedCommand(
                command_name=command.name,
                command_params=dict(command.params),
                run_at=run_at,
                original_text=original_text,
                pre_confirmed=pre_confirmed,
            )
        )
        uow.commit()
    return new_id


def list_pending(uow: DelayedExecutionUnitOfWork) -> list[DelayedCommand]:
    with uow:
        return uow.commands.list_pending()


def cancel(uow: DelayedExecutionUnitOfWork, task_id: int) -> bool:
    with uow:
        cancelled = uow.commands.set_status(task_id, DelayedCommandStatus.CANCELLED)
        uow.commit()
    return cancelled


async def run_due(
    uow: DelayedExecutionUnitOfWork, dispatcher: CommandDispatcher, now: datetime | None = None
) -> int:
    """Fires every pending command whose run_at has arrived. Each is marked
    DONE/FAILED first (so a crash mid-dispatch can't replay it on the next
    poll) and dispatched through dispatch_preconfirmed when it was confirmed
    at schedule time — the timer has nobody to answer a confirmation prompt.
    Returns how many were handled, for the poller's log line."""
    now = now or datetime.now()
    with uow:
        due = [task for task in uow.commands.list_pending() if task.is_due(now)]
        for task in due:
            assert task.id is not None
            uow.commands.set_status(task.id, DelayedCommandStatus.DONE)
        uow.commit()

    for task in due:
        assert task.id is not None
        failed = False
        try:
            if task.pre_confirmed:
                response = await dispatcher.dispatch_preconfirmed(task.command_name, task.command_params)
            else:
                response = await dispatcher.dispatch(task.command_name, task.command_params)
            # dispatch() swallows a handler exception into a FAILED response
            # rather than raising, so the status is the real signal here.
            failed = response.status is CommandStatus.FAILED
            logger.info(
                "Delayed command %s (%s) fired: status=%s", task.id, task.command_name, response.status.value
            )
        except Exception:
            logger.exception("Delayed command %s (%s) failed to fire", task.id, task.command_name)
            failed = True
        if failed:
            with uow:
                uow.commands.force_status(task.id, DelayedCommandStatus.FAILED)
                uow.commit()

    return len(due)
