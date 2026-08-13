from __future__ import annotations

import asyncio
from typing import Any

from core.dispatcher import CommandDispatcher
from core.os_adapter import get_os_adapter


async def _handle_ui_action(params: dict[str, Any]) -> dict[str, Any]:
    """A dumb executor, exactly like core/dispatcher.py's _handle_open_app —
    it never grounds anything itself. By the time this runs, `steps` is
    already a list of fully-resolved, plain-primitive action dicts (see
    modules.ui_automation.service_layer.to_command_params); the actual
    grounding (free text -> which element, via
    modules.ui_automation.service_layer.ground_instruction) happens earlier,
    in the pre-dispatch hook of core/voice/pipeline.py or
    core/voice/web_pipeline.py, exactly where open_app/open_media/
    schedule_event's own param resolution happens for those commands."""
    steps = params.get("steps")
    if not steps or not isinstance(steps, list):
        raise ValueError("Missing required parameter 'steps'")

    adapter = get_os_adapter()
    for step in steps:
        action = step.get("action")
        if action == "click":
            await asyncio.to_thread(
                adapter.click, int(step["x"]), int(step["y"]), step.get("button", "left")
            )
        elif action == "type_text":
            await asyncio.to_thread(adapter.type_text, step["text"])
        elif action == "press_key":
            await asyncio.to_thread(adapter.press_key, step["key"])
        else:
            raise ValueError(f"Unknown ui_action step action '{action}'")

    return {"steps": steps, "message": params.get("announcement") or "Готово."}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "ui_action",
        _handle_ui_action,
        # dangerous=True — a click/type_text/press_key sequence is full
        # remote control of this machine's mouse and keyboard (e.g. type
        # arbitrary text into a focused terminal, then press_key "Return").
        # core/main.py's POST /api/command is an unauthenticated pass-
        # through listening on the LAN by default (see modules/messaging's
        # equivalent finding for messaging_reply): dangerous=False here
        # would let any device on the network drive this machine with zero
        # confirmation. The live voice loop's own resolver
        # (core/voice/pipeline.py._resolve_ui_action) already speaks the
        # planned action aloud before dispatching and auto-confirms right
        # after, so the "speak, don't block" UX the user asked for is
        # unaffected by this flag — it only closes the raw-API bypass.
        dangerous=True,
        description=(
            "Click, type text, or press a key inside the currently active application window, "
            "grounded automatically against its visible UI from a free-text instruction (raw_text) "
            "— e.g. 'нажми на тренды', 'напечатай текст письма'. Use this for any request to "
            "interact with whatever the user currently has open/focused, when no other command fits."
        ),
    )
