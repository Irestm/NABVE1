from __future__ import annotations

import asyncio
from typing import Any

from core.dispatcher import CommandDispatcher
from core.os_adapter import get_os_adapter


async def _handle_open_media(params: dict[str, Any]) -> dict[str, Any]:
    # `target` is always a fully-resolved URL by the time this handler runs
    # — core/voice/pipeline.py's _resolve_media_target (and the web thin
    # client's equivalent) fill it in from a mood-based recommendation
    # before dispatch, same shape as open_app's target-resolution step.
    target = params.get("target")
    if not target:
        raise ValueError("Не указана цель для открытия.")
    adapter = get_os_adapter()
    success = await asyncio.to_thread(adapter.open_application, target)
    if not success:
        raise RuntimeError(f"Не удалось открыть «{target}».")
    return {"target": target}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "open_media",
        _handle_open_media,
        dangerous=False,
        description="Открыть музыкальную или видео-рекомендацию на YouTube (target, уже готовый URL).",
    )
