from __future__ import annotations

from typing import Any, Protocol

from core.dispatcher import CommandDispatcher


class _DiscussionCapableLoop(Protocol):
    def request_discussion_mode(self) -> bool: ...
    def request_end_discussion(self) -> bool: ...


def register_commands(dispatcher: CommandDispatcher, voice_loop: _DiscussionCapableLoop) -> None:
    """Registers "discussion_start" / "discussion_stop" — button/API ways
    into and out of modules/discussion_mode without a spoken phrase. The mode
    itself runs inside the mic loop (see core/voice/pipeline.py's
    _run_discussion_mode), so these only signal that loop; they need the
    voice loop, hence the extra argument and the bootstrap-only registration."""

    async def _handle_discussion_start(_params: dict[str, Any]) -> dict[str, Any]:
        if not voice_loop.request_discussion_mode():
            raise RuntimeError(
                "Голосовой ассистент не запущен — режим дискуссии доступен только при активном микрофоне."
            )
        return {"message": "Включаю режим дискуссии — слушаю вашу беседу."}

    async def _handle_discussion_stop(_params: dict[str, Any]) -> dict[str, Any]:
        if not voice_loop.request_end_discussion():
            raise RuntimeError("Режим дискуссии сейчас не активен.")
        return {"message": "Заканчиваю дискуссию."}

    dispatcher.register(
        "discussion_start",
        _handle_discussion_start,
        dangerous=False,
        description=(
            "Включить режим дискуссии: ассистент молча слушает беседу и высказывает мнение по "
            "кодовой фразе «что думаешь, <имя>»; выход — фразой «выйди из режима дискуссии»."
        ),
    )
    dispatcher.register(
        "discussion_stop",
        _handle_discussion_stop,
        dangerous=False,
        description="Закончить режим дискуссии (равносильно фразе «выйди из режима дискуссии»).",
    )
