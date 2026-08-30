from __future__ import annotations

from core.ai_adapter_chain import candidate_chain
from core.logger import get_logger

logger = get_logger(__name__)

_FALLBACK = "Пока не могу сформулировать мнение — не набралось контекста разговора."


def _build_prompt(transcript: str, assistant_name: str | None, language: str) -> str:
    who = assistant_name or "ассистент"
    return (
        f"Ты — {who}. Ты молча слушал разговор двух людей и теперь тебя прямо спросили, "
        f"что ты думаешь. Вот последняя часть разговора (реплики помечены спикерами):\n\n"
        f"{transcript}\n\n"
        f"Коротко (2–4 предложения) обобщи суть спора и выскажи собственную обоснованную "
        f"точку зрения — не пересказ, а именно мнение. Отвечай на языке '{language}'. "
        f"Без вступлений вроде «как ассистент»."
    )


async def build_opinion(transcript: str, assistant_name: str | None, language: str = "ru") -> str:
    """Runs the accumulated discussion transcript through the AI adapter
    chain and returns Jarvis's spoken-style opinion. The assistant's
    personality/name are applied by each adapter's own apply_system_prompt,
    so the result still sounds like Jarvis, not a neutral summary."""
    if not transcript.strip():
        return _FALLBACK

    prompt = _build_prompt(transcript, assistant_name, language)
    for adapter in candidate_chain(transcript):
        try:
            reply = await adapter.send_prompt(prompt, fast_mode=False)
        except Exception as exc:
            logger.warning("Opinion adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue
        if reply and reply.strip():
            return reply.strip()

    return "Не получилось связаться с ИИ, чтобы обдумать это. Попробуйте ещё раз."
