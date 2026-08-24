from __future__ import annotations

from core.ai_adapter_chain import candidate_chain
from core.logger import get_logger

logger = get_logger(__name__)


def _build_prompt(query: str) -> str:
    return (
        f'Это поисковый запрос для YouTube, полученный из распознавания голоса. Пользователь мог '
        f'произнести иностранное (обычно английское) название — игры, фильма, канала, исполнителя, '
        f'мема и т.п. — а распознавание речи записало его фонетически кириллицей вместо оригинального '
        f'написания (например: "дед селс" вместо "Dead Cells", "рик энд морти" вместо "Rick and Morty"). '
        f'Вот запрос: "{query}". Если в нём есть такие фонетически искажённые иностранные слова — верни '
        f'запрос с исправленным написанием этих слов (остальной текст, включая обычные русские слова, не '
        f'трогай). Если всё уже написано правильно (или иностранных слов нет вообще) — верни запрос БЕЗ '
        f'ИЗМЕНЕНИЙ. Ответь ТОЛЬКО итоговым поисковым запросом, без кавычек и пояснений.'
    )


async def correct_query(query: str) -> str:
    """Best-effort correction of a YouTube search query built straight from
    raw STT output (see core/voice/pipeline.py._resolve_media_target and
    core/voice/web_pipeline.py._resolve_and_dispatch's open_media branch): a
    phonetic Cyrillic transliteration of a foreign title ("дед селс" for
    "Dead Cells") searches nothing like the real thing, so "открой видео X"
    for anything with a foreign name routinely returned wrong/no results on
    the first try. modules.app_catalog.resolver already solves the same
    underlying problem for "открой X" (an app/game to launch, matched
    against a list of what's actually installed) — this is the open_media
    equivalent, except there's no catalog to match against here, just a
    free-text search query handed to an AI adapter to clean up.

    Tries candidate_chain()'s adapters in order (local model, then the
    ai_bridge cloud chain — same order used everywhere else an AI call
    doesn't have its own reason to prefer cloud first). Falls back to the
    original, uncorrected query — never None, never raises — on total
    failure: an uncorrected search is still strictly better than no search
    at all, and the caller has no other fallback to offer here."""
    query = query.strip()
    if not query:
        return query

    prompt = _build_prompt(query)
    for adapter in candidate_chain(query):
        try:
            raw = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            logger.warning("Media query correction adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue

        corrected = raw.strip().strip('"').strip("'").strip()
        if corrected:
            return corrected

    return query
