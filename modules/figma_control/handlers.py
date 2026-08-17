from __future__ import annotations

from typing import Any

from core.dispatcher import CommandDispatcher
from modules.figma_control.dispatcher import process_figma_command


async def _handle_figma_command(params: dict[str, Any]) -> dict[str, Any]:
    text = params.get("text")
    if not text:
        raise ValueError("Missing required parameter 'text'")
    message = await process_figma_command(str(text))
    return {"message": message}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "figma_command",
        _handle_figma_command,
        dangerous=False,
        description=(
            "Execute a voice command inside the Figma design tool — create, select, move, resize, "
            "delete, recolor, group, or align layers/frames/shapes, export a selection, undo/redo "
            "(text: the raw spoken command)."
        ),
    )
