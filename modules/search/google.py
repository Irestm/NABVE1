from __future__ import annotations

import re
import urllib.parse

from core.logger import get_logger

logger = get_logger(__name__)

_CONSENT_BUTTON_PATTERN = re.compile(r"accept all|i agree|reject all", re.IGNORECASE)


async def search(query: str, num_results: int = 3) -> list[dict[str, str]]:
    from playwright.async_api import async_playwright

    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://www.google.com/search?q={encoded_query}&hl=en"

    results: list[dict[str, str]] = []
    playwright_ctx = await async_playwright().start()
    browser = await playwright_ctx.chromium.launch(headless=True)
    try:
        page = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded")

        try:
            consent_button = page.get_by_role("button", name=_CONSENT_BUTTON_PATTERN)
            await consent_button.click(timeout=3000)
        except Exception as exc:
            # Expected on most non-EU requests, where Google shows no consent
            # dialog at all — debug, not warning, to avoid log spam.
            logger.debug("No Google consent dialog to dismiss: %s", exc)

        try:
            await page.wait_for_selector("#search a h3", timeout=10000)
            # Google's markup for search results is undocumented and changes
            # without notice, and this cannot be live-tested against real
            # Google from this sandboxed environment, so these selectors may
            # need adjustment if Google changes its DOM structure.
            headers = page.locator("#search a h3")
            count = await headers.count()
            for i in range(min(count, num_results)):
                try:
                    header = headers.nth(i)
                    title = await header.inner_text()
                    link = header.locator("xpath=ancestor::a[1]")
                    href = await link.get_attribute("href")
                    if not href:
                        continue
                    snippet = ""
                    try:
                        container = header.locator(
                            "xpath=ancestor::div[@data-hveid or @data-sokoban-container][1]"
                        )
                        snippet = await container.inner_text()
                        snippet = snippet.replace(title, "", 1).strip()
                        snippet = " ".join(snippet.splitlines()).strip()
                    except Exception:
                        # Cosmetic (a result without a snippet is still
                        # usable) but still worth a trace if it starts
                        # failing on every result — that's the systematic-
                        # markup-change case this module's own docstring
                        # warns about, not a one-off.
                        snippet = ""
                        logger.debug("Failed to extract a search result's snippet", exc_info=True)
                    results.append({"title": title.strip(), "url": href, "snippet": snippet})
                except Exception:
                    logger.warning("Failed to parse a search result entry", exc_info=True)
                    continue
        except Exception:
            logger.warning("Failed to locate Google search results for query '%s'", query, exc_info=True)
    finally:
        await browser.close()
        await playwright_ctx.stop()

    return results


class GoogleSearchAdapter:
    """Adapter satisfying modules.search.ports.WebSearchPort."""

    search = staticmethod(search)


def build_summary(results: list[dict[str, str]]) -> str:
    if not results:
        return "No results found."

    lines: list[str] = []
    for index, result in enumerate(results, start=1):
        title = result.get("title", "").strip()
        snippet = result.get("snippet", "").strip()
        if snippet:
            lines.append(f"{index}. {title}. {snippet}")
        else:
            lines.append(f"{index}. {title}.")

    return "\n".join(lines)
