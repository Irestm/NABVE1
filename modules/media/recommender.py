from __future__ import annotations

from core.ai_adapter_chain import candidate_chain
from core.logger import get_logger

logger = get_logger(__name__)

_KIND_SUBJECT: dict[str, str] = {"music": "песню", "video": "видео"}


def _build_prompt(kind: str, mood: str) -> str:
    subject = _KIND_SUBJECT.get(kind, "видео")
    return (
        f'Настроение пользователя сейчас: "{mood}". Посоветуй одну конкретную {subject}, которая подойдёт '
        "под это настроение. Ответь ТОЛЬКО поисковым запросом для YouTube (например, исполнитель и "
        "название песни, или тема видео) — без пояснений, кавычек и лишних слов."
    )


async def recommend(kind: str, mood: str) -> str | None:
    """Turns a spoken mood into a concrete YouTube search query, trying
    candidate_chain()'s adapters in order (local model, then the
    ai_bridge cloud chain — same as everywhere else an AI call doesn't have
    its own reason to prefer cloud first). Returns None if every adapter
    failed or replied with nothing usable; the caller then falls back to
    the same "not understood" response used elsewhere when an AI call comes
    back empty-handed."""
    prompt = _build_prompt(kind, mood)
    for adapter in candidate_chain(prompt):
        try:
            raw = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            logger.warning("Media recommendation adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue

        query = raw.strip().strip('"').strip("'").strip()
        if query:
            return query

    return None
