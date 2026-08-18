from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any

from core.browser_automation import HIDE_WEBDRIVER_INIT_SCRIPT, resolve_browser_launcher
from core.browser_cookie_import import ImportResult, import_session_cookies
from core.config import DATA_DIR
from core.logger import get_logger
from modules.ai_bridge import virtual_display

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
    """Persistent Playwright session for the user's own Quizlet account
    (engine picked by core.browser_automation.resolve_browser_launcher —
    Firefox by default). Uses the same launch_persistent_context
    (user_data_dir=...) mechanism as
    modules.ai_bridge.providers.base.BrowserProviderAdapter — the browser
    itself persists cookies/localStorage on disk across restarts, no
    bespoke storage_state export/import needed.

    Renders on modules.ai_bridge.virtual_display's hidden Xvfb display by
    default — same reasoning as BrowserProviderAdapter: real headed
    rendering (Cloudflare's bot-check needs it — see the captcha-loop
    investigation this module was built for) without a window actually
    appearing on the user's screen for a purely programmatic action like
    scraping/importing. open_login_page() is the one exception: logging in
    is a one-time, user-visible action (the user types their own Quizlet
    password directly into quizlet.com — this module never sees or stores
    it) — it forces a relaunch on the real display so there's something to
    look at, mirroring BrowserProviderAdapter.reveal()."""

    def __init__(self) -> None:
        self._playwright: Any = None
        self._context: Any = None
        self._page: Any = None
        self._on_virtual_display = False
        self._lock = asyncio.Lock()

    async def _ensure_page(self, *, force_headed: bool = False) -> Any:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright is not installed. Install it with: "
                "pip install playwright && playwright install firefox chromium"
            ) from exc

        if self._context is not None and force_headed and self._on_virtual_display:
            # Currently hidden on the virtual display but a human needs to
            # actually see this now (login) — tear down and relaunch on the
            # real display below, mirroring BrowserProviderAdapter.reveal().
            # Inlined rather than calling self.close(): every caller of
            # _ensure_page already holds self._lock, and that method
            # re-acquires it (asyncio.Lock isn't reentrant).
            try:
                await self._context.close()
            except Exception as context_already_gone:
                logger.debug(
                    "Error closing virtual-display Quizlet context before reveal: %s",
                    context_already_gone,
                    exc_info=True,
                )
            finally:
                self._context = None
                self._page = None
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception as driver_already_stopped:
                    logger.debug(
                        "Playwright driver already stopped before reveal: %s",
                        driver_already_stopped,
                        exc_info=True,
                    )
                finally:
                    self._playwright = None

        if self._context is not None:
            try:
                if self._page is None or self._page.is_closed():
                    self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
                return self._page
            except Exception as exc:
                # This module-level session can outlive the actual browser
                # window it opened — the user (or an OS sleep/crash) can
                # close it between requests while this object still thinks
                # it's alive, so the next Playwright call fails with a raw,
                # low-level "Target page, context or browser has been
                # closed" instead of anything actionable. Discard the stale
                # references and fall through to relaunch below rather than
                # leaving every subsequent Quizlet action broken until the
                # whole backend restarts.
                logger.warning("Quizlet browser context was closed unexpectedly, relaunching: %s", exc)
                self._context = None
                self._page = None
                if self._playwright is not None:
                    try:
                        await self._playwright.stop()
                    except Exception as driver_already_stopped:
                        logger.debug(
                            "Playwright driver already stopped: %s", driver_already_stopped, exc_info=True
                        )
                    finally:
                        self._playwright = None

        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        # See core.browser_automation.resolve_browser_launcher: prefers
        # Firefox, which — confirmed by hand — doesn't trip the same
        # repeat-captcha bot-detection friction Playwright's default
        # Chromium build ("Chrome for Testing") does on quizlet.com.
        browser_type, engine_kwargs = resolve_browser_launcher(self._playwright)
        launch_kwargs: dict[str, Any] = {
            "user_data_dir": str(PROFILE_DIR),
            "headless": False,
            "viewport": {"width": 1280, "height": 800},
            **engine_kwargs,
        }
        self._on_virtual_display = False
        if not force_headed:
            display = await virtual_display.get_display()
            if display:
                launch_kwargs["env"] = {**os.environ, "DISPLAY": display}
                self._on_virtual_display = True
        self._context = await browser_type.launch_persistent_context(**launch_kwargs)
        await self._context.add_init_script(HIDE_WEBDRIVER_INIT_SCRIPT)
        logger.info(
            "Launched persistent Quizlet browser context (engine=%s, virtual_display=%s) at %s",
            browser_type.name,
            self._on_virtual_display,
            PROFILE_DIR,
        )
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        return self._page

    async def open_login_page(self) -> None:
        """Reveals a visible window on Quizlet's own login page so the user
        can log in themselves."""
        async with self._lock:
            page = await self._ensure_page(force_headed=True)
            await page.goto(LOGIN_URL, wait_until="domcontentloaded")
            await page.bring_to_front()

    @property
    def lock(self) -> asyncio.Lock:
        """Exposed for quizlet_scraper's multi-step operations
        (list_library_sets/scrape_set_terms), which need EXCLUSIVE use of
        the shared page across several awaits — navigate, scroll, scan — not
        just while acquiring it. Every method on this class used to only
        hold self._lock around page *acquisition* (_ensure_page) and then
        navigate/read afterward with the lock already released, which let
        two concurrent Quizlet operations (e.g. two "Импортировать" clicks
        in quick succession, or a bulk import racing a status poll) navigate
        the one shared page out from under each other mid-scrape — confirmed
        live: five concurrent scrape_set_terms calls all landing on the
        exact same URL and finding zero terms, right after a lock-scoped
        run against the same account found all 25 sets correctly. Callers
        that need the page across multiple awaits must do
        `async with session.lock:` themselves and then call
        navigate_to_library_locked()/`_ensure_page()` — never
        library_page(), which re-acquires this same non-reentrant lock and
        would deadlock nested inside another lock() block."""
        return self._lock

    async def navigate_to_library_locked(self) -> Any:
        """Same steps as library_page(), for a caller that already holds
        `self.lock` for a longer multi-step operation — see that
        property's docstring for why this split exists."""
        page = await self._ensure_page()
        if "quizlet.com" not in page.url:
            await page.goto(LIBRARY_URL, wait_until="domcontentloaded")
        return page

    async def library_page(self) -> Any:
        """Page navigated to the user's library — for a caller that only
        needs the page for one immediate operation of its own (nothing else
        in this file currently calls this; kept for any single-step,
        stand-alone caller). Doesn't force a fresh navigation if already
        somewhere on quizlet.com, so a scrape right after login doesn't
        lose the just-authenticated tab."""
        async with self._lock:
            return await self.navigate_to_library_locked()

    async def is_logged_in(self) -> bool:
        """Never launches a browser just to check — a session that isn't
        already open this process lifetime honestly reports "not connected"
        rather than popping up a window on every status poll (same
        reasoning as BrowserProviderAdapter.is_logged_in). The persisted
        Chromium profile itself is untouched either way, so the very next
        login/refresh/import call still picks up the real saved session.

        Holds self._lock for the whole navigate+read, not just page
        acquisition — see the `lock` property's docstring for why that
        used to be a race with concurrent list_library_sets/
        scrape_set_terms calls."""
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


async def import_session() -> ImportResult:
    """Copies an already-logged-in quizlet.com session from the user's own
    real Firefox/Chrome browser into the automation profile — bypasses
    Quizlet's Cloudflare bot-check entirely rather than trying to pass a
    fresh automated login through it (see the captcha-loop investigation
    this was built for)."""
    session = get_session()
    if not PROFILE_DIR.exists():
        # Bootstrap: launch once just to materialize a real profile skeleton
        # (cookies.sqlite etc.) for the writer below to write into. Locked
        # like every other _ensure_page() call — see QuizletSession.lock's
        # docstring for why an unlocked call here could still race a
        # concurrent list_library_sets/scrape_set_terms/is_logged_in.
        async with session.lock:
            await session._ensure_page()
    # Never write into cookies.sqlite while a live context has it open —
    # Firefox's own WAL writes could clobber or race with ours.
    await session.close()
    result = await asyncio.to_thread(import_session_cookies, PROFILE_DIR, ["quizlet.com"])
    # Reopen right away so the freshly-imported cookies actually take effect —
    # is_logged_in()/library_page() never launch a browser just to check (see
    # their own docstrings), so without this the very next status poll would
    # still see self._context as None and report "Гость" until something
    # else happened to open it.
    async with session.lock:
        await session._ensure_page()
    return result


async def logout() -> None:
    """Full session reset: closes the browser context (if open) and wipes
    its persistent profile directory, so the next launch starts as a fresh
    guest session."""
    session = get_session()
    await session.close()
    if PROFILE_DIR.exists():
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)
    logger.info("Reset Quizlet session to guest (profile directory cleared)")
