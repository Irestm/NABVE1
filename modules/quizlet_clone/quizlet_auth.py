from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

from core.config import DATA_DIR
from core.logger import get_logger

logger = get_logger(__name__)

PROFILE_DIR: Path = DATA_DIR / "browser_profiles" / "quizlet"
LIBRARY_URL = "https://quizlet.com/latest"
LOGIN_URL = "https://quizlet.com/login"

# Same "scan the visible text for a sign-in invitation" approach as
# modules.ai_bridge.providers.base.BrowserProviderAdapter.guest_markers —
# a login button's exact markup is exactly the kind of thing a redesign
# changes without notice, whereas "some text invites you to sign in" is a
# much sturdier signal.
GUEST_MARKERS = ("log in", "sign up", "войти", "увійти", "зарегистр")


class QuizletSession:
    """Persistent Playwright/Chromium session for the user's own Quizlet
    account. Uses the same launch_persistent_context(user_data_dir=...)
    mechanism as modules.ai_bridge.providers.base.BrowserProviderAdapter —
    Chromium itself persists cookies/localStorage on disk across restarts,
    no bespoke storage_state export/import needed.

    Unlike ai_bridge's adapters, this never renders on a hidden virtual
    display: logging in is a one-time, user-visible action (the user types
    their own Quizlet password directly into quizlet.com — this module
    never sees or stores it), and a brief visible window while scraping a
    refresh is reassuring rather than something to hide.
    """

    def __init__(self) -> None:
        self._playwright: Any = None
        self._context: Any = None
        self._page: Any = None
        self._lock = asyncio.Lock()

    async def _ensure_page(self) -> Any:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright is not installed. Install it with: "
                "pip install playwright && playwright install chromium"
            ) from exc

        if self._context is None:
            PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            self._playwright = await async_playwright().start()
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=False,
                args=["--window-size=1280,800"],
            )
            logger.info("Launched persistent Quizlet browser context at %s", PROFILE_DIR)

        if self._page is None or self._page.is_closed():
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        return self._page

    async def open_login_page(self) -> None:
        """Reveals a visible window on Quizlet's own login page so the user
        can log in themselves."""
        async with self._lock:
            page = await self._ensure_page()
            await page.goto(LOGIN_URL, wait_until="domcontentloaded")
            await page.bring_to_front()

    async def library_page(self) -> Any:
        """Page navigated to the user's library — reused by
        quizlet_scraper. Doesn't force a fresh navigation if already
        somewhere on quizlet.com, so a scrape right after login doesn't
        lose the just-authenticated tab."""
        async with self._lock:
            page = await self._ensure_page()
            if "quizlet.com" not in page.url:
                await page.goto(LIBRARY_URL, wait_until="domcontentloaded")
            return page

    async def is_logged_in(self) -> bool:
        """Never launches a browser just to check — a session that isn't
        already open this process lifetime honestly reports "not connected"
        rather than popping up a window on every status poll (same
        reasoning as BrowserProviderAdapter.is_logged_in). The persisted
        Chromium profile itself is untouched either way, so the very next
        login/refresh/import call still picks up the real saved session."""
        if self._context is None:
            return False
        async with self._lock:
            page = await self._ensure_page()
        try:
            if "quizlet.com" not in page.url:
                await page.goto(LIBRARY_URL, wait_until="domcontentloaded")
            body_text = (await page.locator("body").inner_text()).lower()
        except Exception as exc:
            logger.debug("Could not read Quizlet page text to check login status: %s", exc)
            return False
        return not any(marker in body_text for marker in GUEST_MARKERS)

    async def close(self) -> None:
        async with self._lock:
            if self._context is not None:
                try:
                    await self._context.close()
                except Exception as context_already_gone:
                    logger.debug("Error closing Quizlet browser context: %s", context_already_gone, exc_info=True)
                finally:
                    self._context = None
                    self._page = None
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception as driver_already_stopped:
                    logger.debug("Error stopping Quizlet playwright driver: %s", driver_already_stopped, exc_info=True)
                finally:
                    self._playwright = None
            logger.info("Closed Quizlet browser context.")


_session: QuizletSession | None = None


def get_session() -> QuizletSession:
    global _session
    if _session is None:
        _session = QuizletSession()
    return _session


async def is_logged_in() -> bool:
    return await get_session().is_logged_in()


async def login() -> None:
    """Opens a visible browser window on Quizlet's own login page so the
    user can log in themselves — Jarvis never asks for or stores the
    Quizlet password. Once logged in, the persistent browser profile keeps
    the session for future runs."""
    await get_session().open_login_page()


async def logout() -> None:
    """Full session reset: closes the browser context (if open) and wipes
    its persistent profile directory, so the next launch starts as a fresh
    guest session."""
    session = get_session()
    await session.close()
    if PROFILE_DIR.exists():
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)
    logger.info("Reset Quizlet session to guest (profile directory cleared)")
