from __future__ import annotations

import asyncio
from typing import Any

from core.dispatcher import CommandDispatcher
from modules.delayed_execution import service_layer
from modules.delayed_execution.uow import DelayedExecutionUnitOfWork


def _describe(task) -> str:
    return f"№{task.id}: {task.original_text} — в {task.run_at.strftime('%H:%M')}"


async def _handle_delayed_list(_params: dict[str, Any]) -> dict[str, Any]:
    tasks = await asyncio.to_thread(service_layer.list_pending, DelayedExecutionUnitOfWork())
    if not tasks:
        return {"tasks": [], "message": "Отложенных задач нет."}
    listed = "; ".join(_describe(task) for task in tasks)
    return {
        "tasks": [
            {
                "id": task.id,
                "original_text": task.original_text,
                "command_name": task.command_name,
                "run_at": task.run_at.isoformat(),
            }
            for task in tasks
        ],
        "message": f"Отложенные задачи: {listed}.",
    }


async def _handle_delayed_cancel(params: dict[str, Any]) -> dict[str, Any]:
    task_id = params.get("task_id")
    if task_id is None:
        raise ValueError("Не указан номер отложенной задачи.")
    cancelled = await asyncio.to_thread(
        service_layer.cancel, DelayedExecutionUnitOfWork(), int(task_id)
    )
    if not cancelled:
        raise RuntimeError(f"Отложенная задача №{task_id} не найдена или уже выполнена.")
    return {"task_id": int(task_id), "cancelled": True, "message": f"Отложенная задача №{task_id} отменена."}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "delayed_list",
        _handle_delayed_list,
        dangerous=False,
        description="Показать отложенные (запланированные на потом) команды.",
    )
    dispatcher.register(
        "delayed_cancel",
        _handle_delayed_cancel,
        dangerous=False,
        description="Отменить отложенную команду по её номеру (task_id).",
    )
