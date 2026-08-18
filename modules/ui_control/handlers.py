from __future__ import annotations

from typing import Any

from core.dispatcher import CommandDispatcher
from core.state import state_manager
from modules.ui_control import service_layer


async def _handle_show_window(_params: dict[str, Any]) -> dict[str, Any]:
    service_layer.show_window(state_manager)
    return {"action": "show"}


async def _handle_hide_window(_params: dict[str, Any]) -> dict[str, Any]:
    service_layer.hide_window(state_manager)
    return {"action": "hide"}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "show_window",
        _handle_show_window,
        dangerous=False,
        description="Показать и сфокусировать окно NABVE.",
    )
    dispatcher.register(
        "hide_window",
        _handle_hide_window,
        dangerous=False,
        description="Скрыть окно NABVE (продолжает работать в трее).",
    )
