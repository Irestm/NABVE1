from __future__ import annotations

from typing import Any, Protocol

from core.dispatcher import CommandDispatcher


class _DiscussionCapableLoop(Protocol):
    def request_discussion_mode(self) -> bool: ...


def register_commands(dispatcher: CommandDispatcher, voice_loop: _DiscussionCapableLoop) -> None:
    """Registers the "discussion_start" command — a button/API way into
    modules/discussion_mode without a spoken trigger phrase. The mode itself
    still runs inside the mic loop (see core/voice/pipeline.py's
    _run_discussion_mode), so all this does is signal that loop; it needs
    the voice loop, hence the extra argument and the bootstrap-only
    registration."""

    async def _handle_discussion_start(_params: dict[str, Any]) -> dict[str, Any]:
        if not voice_loop.request_discussion_mode():
            raise RuntimeError(
                "Голосовой ассистент не запущен — режим дискуссии доступен только при активном микрофоне."
            )
        return {"message": "Включаю режим дискуссии — слушаю вашу беседу."}

    dispatcher.register(
        "discussion_start",
        _handle_discussion_start,
        dangerous=False,
        description=(
            "Включить режим дискуссии: ассистент молча слушает беседу и высказывает мнение по "
            "кодовой фразе «что думаешь, <имя>»; выход — фразой «выйди из режима дискуссии»."
        ),
    )
