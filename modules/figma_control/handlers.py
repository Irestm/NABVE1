from __future__ import annotations

from typing import Any

from core.dispatcher import CommandDispatcher
from modules.figma_control.dispatcher import process_figma_command


async def _handle_figma_command(params: dict[str, Any]) -> dict[str, Any]:
    text = params.get("text")
    if not text:
        raise ValueError("Не указан текст команды.")
    message = await process_figma_command(str(text))
    return {"message": message}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "figma_command",
        _handle_figma_command,
        dangerous=False,
        description=(
            "Выполнить голосовую команду внутри Figma — создать, выделить, переместить, изменить "
            "размер, удалить, перекрасить, сгруппировать или выровнять слои/фреймы/фигуры, "
            "экспортировать выделенное, отменить/повторить (text: сырой текст команды)."
        ),
    )
