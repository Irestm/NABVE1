from __future__ import annotations

import json
import re

from core.ai_adapter_chain import local_first_chain
from core.logger import get_logger

logger = get_logger(__name__)

_JSON_ARRAY_PATTERN = re.compile(r"\[.*\]", re.DOTALL)

# Kept well under any adapter's context window — a set page's own visible
# text (after the caller strips it down, see quizlet_scraper.py) is at most
# a few thousand characters even for a large set; this cap is a safety net
# against an unexpectedly bloated page, not the normal case.
_MAX_PAGE_TEXT_CHARS = 12_000

_TERMS_PROMPT = (
    "Вот видимый текст страницы одного набора карточек Quizlet (термин и его определение, "
    "могут чередоваться в любом порядке — иногда термин идёт первым, иногда определение). "
    "Найди в этом тексте все пары термин/определение, которые относятся к самому набору "
    "карточек. Игнорируй меню сайта, кнопки, рекламу, футер, счётчики, имена пользователей и всё, "
    "что не является содержимым карточек. Ответь ТОЛЬКО JSON-массивом объектов вида "
    '[{"term": "...", "definition": "..."}, ...], без каких-либо пояснений до или после. '
    "Если не можешь найти ни одной настоящей пары — верни [].\n\n"
    "Текст страницы:\n"
)


def _parse_pairs(raw: str) -> list[tuple[str, str]]:
    match = _JSON_ARRAY_PATTERN.search(raw)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    pairs: list[tuple[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        term = item.get("term")
        definition = item.get("definition")
        if isinstance(term, str) and isinstance(definition, str) and term.strip() and definition.strip():
            pairs.append((term.strip(), definition.strip()))
    return pairs


async def extract_terms_via_ai(page_text: str) -> list[tuple[str, str]]:
    """Last-resort fallback for quizlet_scraper.scrape_set_terms when every
    known CSS selector pair fails to find a term/definition list — Quizlet
    has redesigned this exact page enough times (see this module's own
    "Confirmed live" comments) that chasing each markup change by hand
    isn't a lasting fix. Feeds the page's own visible text to whichever AI
    adapter is available (core.ai_adapter_chain.local_first_chain — the
    same local-model-then-cloud-chain modules/calendar/extraction.py uses)
    and asks it to pull out the pairs itself: robust to a shuffled DOM,
    renamed classes, a new wrapper element, anything that only breaks an
    exact selector rather than the actual term/definition text on the page.

    Best-effort and silent on failure (never raises) — returns [] if every
    adapter is unavailable/fails or none of them return anything
    parseable, so the caller's own clear "Quizlet changed its layout"
    error still fires in that case instead of this masking it."""
    prompt = _TERMS_PROMPT + page_text[:_MAX_PAGE_TEXT_CHARS]

    for adapter in local_first_chain():
        try:
            raw = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            logger.warning("Quizlet AI term-extraction adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue

        pairs = _parse_pairs(raw)
        if pairs:
            logger.info("AI fallback extracted %d terms from a Quizlet set page", len(pairs))
            return pairs

    return []
