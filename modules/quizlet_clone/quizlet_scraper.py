from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from core.logger import get_logger
from modules.quizlet_clone.models import LibrarySetSummary
from modules.quizlet_clone.quizlet_auth import QuizletSession

logger = get_logger(__name__)


async def _scroll_and_collect(
    page: Any,
    scan: Callable[[], Awaitable[bool]],
    *,
    max_rounds: int = 25,
    pause_ms: int = 350,
) -> None:
    """Quizlet renders long lists (a user's set library, a set's own term
    list) virtualized — only whatever's currently scrolled into view
    actually exists in the DOM. Confirmed live: a library with dozens of
    sets and a set with dozens of terms both returned the exact same fixed
    count as a much smaller one, because scanning happened once, right
    after load, before anything below the first screenful had ever
    rendered. Just scrolling to the bottom once and re-scanning isn't
    enough either — a windowed/virtualized list can drop earlier items
    back out of the DOM once they scroll out of view, so `scan` must merge
    whatever it currently sees into the *caller's own* accumulator (and
    report whether it found anything new) rather than this helper trying
    to collect a single final snapshot itself. Stops once neither the page
    height nor `scan` are making progress anymore, for two rounds in a row
    (one stalled round can just be a slow render, not the actual end)."""
    previous_height = -1
    stalled_rounds = 0
    for _ in range(max_rounds):
        made_progress = await scan()
        current_height = await page.evaluate("document.body.scrollHeight")
        height_grew = current_height != previous_height
        previous_height = current_height
        if not made_progress and not height_grew:
            stalled_rounds += 1
            if stalled_rounds >= 2:
                return
        else:
            stalled_rounds = 0
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(pause_ms)
    # Ran out of rounds rather than genuinely stabilizing (an unusually
    # long list) — one last scan so whatever the final scroll revealed
    # isn't dropped.
    await scan()

_LAYOUT_CHANGED_HINT = (
    "Не удалось найти {what} — возможно, Quizlet изменил структуру страницы. "
    "Селекторы: modules/quizlet_clone/quizlet_scraper.py"
)

# Quizlet set URLs are built around /<numeric id>/<title-slug> — far more
# stable across redesigns than any CSS class name, so this is the primary
# way library links are recognized (same "scan something structural rather
# than exact markup" idea as quizlet_auth.GUEST_MARKERS). Confirmed live
# (2026-08-18) that the library page's own links are no longer the plain
# root-relative /<id>/<slug>/ this used to assume: they're now absolute
# (https://quizlet.com/...), carry an optional two-letter locale segment
# (/ua/, seen live; presumably others per account language), and end in a
# ?funnelUUID=... tracking query string — matching only the old exact shape
# made every one of them silently invisible to list_library_sets, which is
# why library import stopped finding any sets at all rather than erroring.
_SET_LINK_PATTERN = re.compile(r"^(?:https?://[^/]+)?/(?:[a-z]{2}/)?(\d{5,})(?:/[\w-]*)?/?(?:\?.*)?$")

# The signed-in user's own set library lives at /user/<username>/sets — the
# username makes it impossible to hardcode as a fixed URL (unlike
# quizlet_auth.LIBRARY_URL's /latest), so it's found the same structural way:
# a nav link matching this shape, rather than depending on its (localized,
# redesign-prone) link text. quizlet_auth.LIBRARY_URL's /latest activity feed
# renders its set cards as JS widgets with no plain <a href> at all — this
# nav link is what actually leads to a page with real, scrapeable set links.

# Candidate (term, definition) element-selector pairs to try, in priority
# order, on a set's own page — tried as parallel same-length lists rather
# than one row-wrapper selector, since Quizlet has used several different
# wrapper structures for the same term/definition content over time.
_TERM_DEFINITION_SELECTOR_PAIRS: tuple[tuple[str, str], ...] = (
    ('[data-testid="set-page-term-item-word"]', '[data-testid="set-page-term-item-definition"]'),
    (".SetPageTerm-wordText", ".SetPageTerm-definitionText"),
    ('[class*="TermText" i]', '[class*="DefinitionText" i]'),
)

# Confirmed live (2026-08-18): none of the pairs above still exist. The
# current set page instead renders one element per side (term, then its
# definition, strictly alternating) under this single selector — tried
# first in scrape_set_terms since it's the one actually confirmed working,
# with the pairs above kept as a fallback for older/alternate layouts.
_TERM_CARD_SIDE_SELECTOR = '[data-testid="set-page-term-card-side"]'

_TERM_COUNT_PATTERN = re.compile(r"(\d+)\s*(?:term|термин)", re.IGNORECASE)


async def list_library_sets(session: QuizletSession) -> list[LibrarySetSummary]:
    """Scrapes the signed-in user's Quizlet library: title + term count for
    every set they own. Raises RuntimeError with an explicit "layout may
    have changed" message on total failure — never returns an empty list to
    mean "something went wrong"."""
    page = await session.library_page()

    try:
        # Follow the "your library" nav link like a real user clicking it,
        # rather than page.goto()-ing straight to /user/<name>/sets — a
        # direct jump there was seen (once) to draw an "Access denied" from
        # Quizlet's own bot-detection, whereas clicking through from a page
        # we're already legitimately on didn't. It lives in a dropdown menu
        # that isn't open (element present in the DOM but positioned off in
        # the menu, so Playwright's normal actionability-checked .click()
        # just times out waiting for it to be in-viewport) — dispatch the
        # click via JS instead, which still fires the same React onClick/SPA
        # navigation without needing the menu opened first.
        my_library_link = page.locator("a[href^='/user/'][href$='/sets']").first
        if await my_library_link.count() > 0:
            await my_library_link.evaluate("el => el.click()")
            await page.wait_for_url(re.compile(r"/user/[^/]+/sets"), timeout=15_000)
    except Exception as exc:
        logger.debug("Could not navigate to the user's own Quizlet library: %s", exc, exc_info=True)

    # Must actually be on /user/<name>/sets before scanning for set links —
    # quizlet_auth.LIBRARY_URL (/latest) is a general activity/recommendation
    # feed, not "sets I own", and used to be scanned anyway as a silent
    # fallback whenever the click above failed or the nav link wasn't found
    # at all (e.g. a stale selector after a Quizlet redesign). That fallback
    # is exactly what made list_library_sets return other people's/
    # recommended sets mixed in with the user's own — confirmed against a
    # real user's report ("должен выдавать только мои папки"). Failing loudly
    # here instead means a stale selector shows up as an obvious "не удалось
    # загрузить библиотеку" error to fix, rather than silently returning
    # wrong data that looks like it worked.
    if not re.search(r"/user/[^/]+/sets", page.url):
        raise RuntimeError(
            "Не удалось открыть вашу личную библиотеку Quizlet (только общая лента) — "
            "возможно, Quizlet изменил структуру страницы. Селекторы: modules/quizlet_clone/quizlet_scraper.py"
        )

    try:
        # The URL changes (wait_for_url above) well before the set list
        # itself has actually fetched/rendered — this is a client-rendered
        # React page, and scanning immediately after navigation was
        # confirmed (via a live run) to see only the static page chrome
        # (nav/footer links), zero set cards, every time. Give the async
        # render a moment to settle before scanning for links.
        await page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception as exc:
        logger.debug("Library page didn't reach networkidle in time: %s", exc, exc_info=True)

    seen: dict[str, LibrarySetSummary] = {}
    last_links: list[Any] = []

    async def scan() -> bool:
        nonlocal last_links
        try:
            links = await page.query_selector_all("a[href]")
        except Exception as exc:
            raise RuntimeError(_LAYOUT_CHANGED_HINT.format(what="ссылки на наборы в библиотеке")) from exc
        last_links = links

        found_new = False
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
                container = await link.evaluate_handle(
                    "el => el.closest('article') || el.closest('li') || el.parentElement"
                )
                container_text = await container.as_element().inner_text() if container else ""
                count_match = _TERM_COUNT_PATTERN.search(container_text or "")
                if count_match:
                    term_count = int(count_match.group(1))
            except Exception as term_count_unavailable:
                logger.debug(
                    "Could not read term count for set %s: %s", quizlet_set_id, term_count_unavailable, exc_info=True
                )

            seen[quizlet_set_id] = LibrarySetSummary(quizlet_set_id=quizlet_set_id, title=title, term_count=term_count)
            found_new = True
        return found_new

    await _scroll_and_collect(page, scan)

    if not seen:
        # Diagnostic for exactly this failure — logs every href actually
        # seen on the page (not just ones matching _SET_LINK_PATTERN), so a
        # future layout change shows *what* Quizlet's markup looks like now
        # instead of just "nothing matched."
        try:
            raw_hrefs = [await link.get_attribute("href") for link in last_links]
        except Exception as raw_hrefs_unavailable:
            raw_hrefs = [f"<could not read hrefs: {raw_hrefs_unavailable}>"]
        logger.warning(
            "list_library_sets found no matching set links on %s — saw %d <a href> total, examples: %s",
            page.url,
            len(last_links),
            raw_hrefs[:20],
        )
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
    try:
        await page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception as exc:
        logger.debug("Set page %s didn't reach networkidle in time: %s", quizlet_set_id, exc, exc_info=True)
    # A free-tier account gets a "Quizlet Plus" upsell modal covering the
    # whole set page on most visits (confirmed live, 2026-08-18) — dismiss
    # it before scanning for terms, same as a real user would just close it.
    # Escape alone doesn't close it; the modal's own close icon does.
    try:
        close_button = page.locator('[data-testid="icon-close-x"]').first
        if await close_button.count() > 0:
            await close_button.click(timeout=3_000)
            await page.wait_for_timeout(300)
    except Exception as exc:
        logger.debug("Could not dismiss a possible upsell modal on set %s: %s", quizlet_set_id, exc, exc_info=True)

    last_error: Exception | None = None
    seen_pairs: set[tuple[str, str]] = set()
    pairs: list[tuple[str, str]] = []

    async def scan_card_sides() -> bool:
        nonlocal last_error
        try:
            sides = await page.query_selector_all(_TERM_CARD_SIDE_SELECTOR)
        except Exception as exc:
            last_error = exc
            return False
        # An odd count mid-scroll usually just means a card is half-mounted
        # right now — not a real layout break — so skip this round and let
        # the next one (after another scroll+wait) retry instead of raising.
        if not sides or len(sides) % 2 != 0:
            return False
        found_new = False
        side_texts = [(await el.inner_text()).strip() for el in sides]
        for i in range(0, len(side_texts), 2):
            term_text, definition_text = side_texts[i], side_texts[i + 1]
            if term_text and definition_text and (term_text, definition_text) not in seen_pairs:
                seen_pairs.add((term_text, definition_text))
                pairs.append((term_text, definition_text))
                found_new = True
        return found_new

    try:
        await _scroll_and_collect(page, scan_card_sides)
    except Exception as exc:
        last_error = exc
    if pairs:
        logger.info("Scraped %d terms from Quizlet set %s (card-side selector)", len(pairs), quizlet_set_id)
        return pairs

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

    # Diagnostic for exactly this failure — mirrors list_library_sets' own
    # empty-result logging, so a future layout change shows what Quizlet's
    # markup looks like now instead of just "nothing matched."
    try:
        testids = await page.evaluate(
            "() => Array.from(new Set([...document.querySelectorAll('[data-testid]')]"
            ".map(el => el.getAttribute('data-testid')))).slice(0, 60)"
        )
    except Exception as probe_failed:
        testids = [f"<could not read data-testid values: {probe_failed}>"]
    logger.warning(
        "scrape_set_terms found no terms on set %s (%s) — data-testid values present: %s",
        quizlet_set_id,
        page.url,
        testids,
    )
    raise RuntimeError(_LAYOUT_CHANGED_HINT.format(what="термины набора")) from last_error
