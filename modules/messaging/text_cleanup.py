from __future__ import annotations

from core.ai_adapter_chain import local_first_chain
from core.logger import get_logger

logger = get_logger(__name__)


def _build_prompt(raw_text: str) -> str:
    return (
        "Это текст сообщения, надиктованный голосом для отправки в мессенджере. Расставь знаки "
        "препинания и заглавные буквы там, где это естественно для письменной речи, исправь явные "
        "оговорки/повторы распознавания речи, если они очевидны. НЕ меняй смысл, НЕ добавляй ничего "
        "от себя, НЕ убирай и не смягчай ничего из сказанного. Если текст уже выглядит нормально — "
        f'верни его БЕЗ ИЗМЕНЕНИЙ. Вот текст: "{raw_text}". Ответь ТОЛЬКО итоговым текстом сообщения, '
        "без кавычек и пояснений."
    )


async def clean_dictated_text(raw_text: str) -> str:
    """Best-effort punctuation/capitalization cleanup of a dictated reply
    (see core/voice/pipeline.py._resolve_messaging_reply) before it's read
    back to the user for confirmation and sent — mirrors
    modules.media.query_correction.correct_query's exact contract: tries
    local_first_chain()'s adapters in order, falls back to the original,
    unedited text — never None, never raises — on total failure. An
    unedited dictation is still a perfectly sendable message; failing to
    clean it up is not a reason to block sending."""
    raw_text = raw_text.strip()
    if not raw_text:
        return raw_text

    prompt = _build_prompt(raw_text)
    for adapter in local_first_chain():
        try:
            raw = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            logger.warning("Dictated text cleanup adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue

        cleaned = raw.strip().strip('"').strip("'").strip()
        if cleaned:
            return cleaned

    return raw_text
