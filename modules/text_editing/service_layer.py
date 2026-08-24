from __future__ import annotations

from core.ai_adapter_chain import candidate_chain
from core.logger import get_logger

logger = get_logger(__name__)


class TextEditingError(RuntimeError):
    pass


def _build_prompt(text: str, instruction: str) -> str:
    return (
        f'Вот текст:\n"""{text}"""\n\n'
        f"Инструкция: {instruction}\n\n"
        "Верни ТОЛЬКО отредактированный текст целиком, без пояснений, комментариев "
        "и без кавычек вокруг него."
    )


async def edit_text(text: str, instruction: str) -> str:
    """Tries candidate_chain(instruction)'s adapters in order (same
    complexity-aware routing every other AI call in this codebase uses),
    stopping at the first one that returns something non-empty. Raises
    TextEditingError only if every adapter failed or returned nothing
    usable — same all-or-nothing shape as
    modules.board_games.service_layer.resolve_player_move."""
    prompt = _build_prompt(text, instruction)
    last_error: Exception | None = None
    for adapter in candidate_chain(instruction):
        try:
            result = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            last_error = exc
            logger.warning("Text-editing adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue
        stripped = result.strip()
        if stripped:
            return stripped
    logger.error("All AI adapters failed to edit text: %s", last_error, exc_info=last_error)
    raise TextEditingError("Не удалось отредактировать текст — все AI-адаптеры недоступны.")
