from __future__ import annotations

import re
from typing import Any

from core.logger import get_logger
from modules.quizlet_clone.models import LibrarySetSummary
from modules.quizlet_clone.quizlet_auth import QuizletSession

logger = get_logger(__name__)

_LAYOUT_CHANGED_HINT = (
    "Не удалось найти {what} — возможно, Quizlet изменил структуру страницы. "
    "Селекторы: modules/quizlet_clone/quizlet_scraper.py"
)

# Quizlet set URLs have always looked like /<numeric id>/<title-slug>/ —
# far more stable across redesigns than any CSS class name, so this is the
# primary way library links are recognized (same "scan something structural
# rather than exact markup" idea as quizlet_auth.GUEST_MARKERS).
_SET_LINK_PATTERN = re.compile(r"^/(\d{5,})/([\w-]*)/?$")

# Candidate (term, definition) element-selector pairs to try, in priority
# order, on a set's own page — tried as parallel same-length lists rather
# than one row-wrapper selector, since Quizlet has used several different
# wrapper structures for the same term/definition content over time.
_TERM_DEFINITION_SELECTOR_PAIRS: tuple[tuple[str, str], ...] = (
    ('[data-testid="set-page-term-item-word"]', '[data-testid="set-page-term-item-definition"]'),
    (".SetPageTerm-wordText", ".SetPageTerm-definitionText"),
    ('[class*="TermText" i]', '[class*="DefinitionText" i]'),
)

_TERM_COUNT_PATTERN = re.compile(r"(\d+)\s*(?:term|термин)", re.IGNORECASE)


async def list_library_sets(session: QuizletSession) -> list[LibrarySetSummary]:
    """Scrapes the signed-in user's Quizlet library: title + term count for
    every set they own. Raises RuntimeError with an explicit "layout may
    have changed" message on total failure — never returns an empty list to
    mean "something went wrong"."""
    page = await session.library_page()

    try:
        links = await page.query_selector_all("a[href]")
    except Exception as exc:
        raise RuntimeError(_LAYOUT_CHANGED_HINT.format(what="ссылки на наборы в библиотеке")) from exc

    seen: dict[str, LibrarySetSummary] = {}
    for link in links:
        try:
            href = await link.get_attribute("href")
        except Exception as href_unreadable:
            logger.debug("Could not read href from a library link: %s", href_unreadable, exc_info=True)
            continue
        if not href:
            continue
        match = _SET_LINK_PATTERN.match(href)
        if match is None:
            continue
        quizlet_set_id = match.group(1)
        if quizlet_set_id in seen:
            continue

        try:
            title = (await link.inner_text()).strip()
        except Exception as title_unreadable:
            logger.debug("Could not read title for set %s: %s", quizlet_set_id, title_unreadable, exc_info=True)
            title = ""
        if not title:
            continue

        term_count = 0
        try:
            container = await link.evaluate_handle("el => el.closest('article') || el.closest('li') || el.parentElement")
            container_text = await container.as_element().inner_text() if container else ""
            count_match = _TERM_COUNT_PATTERN.search(container_text or "")
            if count_match:
                term_count = int(count_match.group(1))
        except Exception as term_count_unavailable:
            logger.debug(
                "Could not read term count for set %s: %s", quizlet_set_id, term_count_unavailable, exc_info=True
            )

        seen[quizlet_set_id] = LibrarySetSummary(quizlet_set_id=quizlet_set_id, title=title, term_count=term_count)

    if not seen:
        raise RuntimeError(_LAYOUT_CHANGED_HINT.format(what="наборы в библиотеке Quizlet"))

    logger.info("Found %d sets in the user's Quizlet library", len(seen))
    return list(seen.values())


async def scrape_set_terms(session: QuizletSession, quizlet_set_id: str) -> list[tuple[str, str]]:
    """Extracts every (term, definition) pair from one Quizlet set's own
    page. Raises RuntimeError with an explicit "layout may have changed"
    message if none of the known selector pairs find a consistent,
    non-empty term/definition list."""
    page: Any = await session.library_page()
    try:
        await page.goto(f"https://quizlet.com/{quizlet_set_id}", wait_until="domcontentloaded")
    except Exception as exc:
        raise RuntimeError(f"Не удалось открыть страницу набора {quizlet_set_id} на Quizlet.") from exc

    last_error: Exception | None = None
    for term_selector, definition_selector in _TERM_DEFINITION_SELECTOR_PAIRS:
        try:
            await page.wait_for_selector(term_selector, timeout=15_000, state="visible")
            term_elements = await page.query_selector_all(term_selector)
            definition_elements = await page.query_selector_all(definition_selector)
        except Exception as exc:
            last_error = exc
            continue

        if not term_elements or len(term_elements) != len(definition_elements):
            continue

        pairs: list[tuple[str, str]] = []
        for term_el, definition_el in zip(term_elements, definition_elements):
            term_text = (await term_el.inner_text()).strip()
            definition_text = (await definition_el.inner_text()).strip()
            if term_text and definition_text:
                pairs.append((term_text, definition_text))

        if pairs:
            logger.info("Scraped %d terms from Quizlet set %s", len(pairs), quizlet_set_id)
            return pairs

    raise RuntimeError(_LAYOUT_CHANGED_HINT.format(what="термины набора")) from last_error
