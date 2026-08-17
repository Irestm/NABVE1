from __future__ import annotations

import asyncio
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from core.config import DATA_DIR
from core.logger import get_logger
from modules.ai_bridge import virtual_display

logger = get_logger(__name__)

PROFILES_DIR = DATA_DIR / "browser_profiles"

RESPONSE_WAIT_TIMEOUT_SECONDS = 60
RESPONSE_POLL_INTERVAL_SECONDS = 0.75
RESPONSE_STABLE_READS_REQUIRED = 2
# How long to wait for the prompt input box to actually appear after a fresh
# navigation or right after the previous reply finished — see
# _locate_prompt_box for why this can't be an instant check.
PROMPT_BOX_WAIT_TIMEOUT_MS = 20_000
# A brand-new browser context's very first navigation has to download and
# hydrate the provider's whole JS bundle from nothing — cold disk cache, cold
# V8 compile, and slower software rendering under the hidden Xvfb display
# (see _ensure_page) than a real GPU-accelerated screen — meaningfully
# slower than any later call, which just reuses the same already-warm page.
# 20s was tuned for that warm case; on a cold context it was the actual
# cause of "the very first prompt after a fresh launch reliably fails, and
# never again after that" — the box just genuinely hadn't rendered yet.
COLD_START_PROMPT_BOX_WAIT_TIMEOUT_MS = 45_000


@runtime_checkable
class AIProviderAdapter(Protocol):
    """Common interface every provider adapter implements, so
    `provider_manager` can drive all four providers identically."""

    name: str

    async def open(self, *, reveal: bool = False) -> Any:
        """Open (or reuse) the provider's tab, returning the Playwright page."""
        ...

    async def send_prompt(self, text: str, *, fast_mode: bool = False) -> str:
        """Type `text` into the prompt box, submit it, and return the reply text."""
        ...

    async def is_limit_reached(self) -> bool:
        """Detect from on-page UI markers whether the daily limit was hit."""
        ...

    async def is_logged_in(self) -> bool:
        """Best-effort: whether the current session looks authenticated
        rather than guest."""
        ...

    async def reveal(self) -> None:
        """Bring the provider's background tab/window to the foreground."""
        ...

    async def hide(self) -> None:
        """Send the provider's tab/window back to the background."""
        ...

    async def close(self) -> None:
        """Tear down the browser context, if one is open."""
        ...


class BrowserProviderAdapter(ABC):
    """Shared Playwright persistent-context implementation for a provider
    driven purely through its normal web UI (no API keys). Subclasses only
    need to declare selectors and limit markers for their site; a handful of
    hook methods can be overridden for provider-specific quirks (e.g. a
    "fast model" toggle).

    The browser window is always launched headed (real rendering — confirmed
    the hard way that Gemini specifically detects and blocks headless
    Chromium even with a fully valid, already-authenticated session, so
    `headless=True` is opt-in only via ASSISTANT_AI_BRIDGE_TRY_HEADLESS=1),
    but by default it renders on a hidden Xvfb virtual display (see
    modules.ai_bridge.virtual_display) instead of the user's real screen —
    so it never visibly pops up or steals focus while answering a query.
    `reveal()`/`hide()` — wired to an explicit user command, never called
    automatically — tear the context down and relaunch it on the real
    display (reveal) or back onto the hidden one (hide), since a context
    can't move displays without a fresh launch.
    """

    name: str
    url: str
    profile_dirname: str

    prompt_box_selectors: tuple[str, ...] = ("[contenteditable='true']", "textarea")
    response_block_selectors: tuple[str, ...] = ()
    # Case-insensitive substrings/regex fragments that, if present in the page's
    # visible text, mean the daily/usage limit has been hit. Provider UIs change
    # over time without notice, so this is a best-effort list, not a guarantee.
    limit_markers: tuple[str, ...] = ()
    # Same idea as limit_markers, inverted: if any of these guest-mode
    # invitations ("Sign in", "Log in", ...) are visible on the page, the
    # session is not authenticated. Deliberately text-scanning rather than
    # CSS selectors (like limit_markers) — a login/account button's exact
    # markup is exactly the kind of thing that changes across a redesign
    # without notice, whereas "some visible text invites you to sign in"
    # is a much sturdier signal across UI changes.
    guest_markers: tuple[str, ...] = ("sign in", "log in", "войти", "увійти")

    def __init__(self) -> None:
        self._playwright: Any = None
        self._context: Any = None
        self._page: Any = None
        self._headless = False
        self._on_virtual_display = False
        self._lock = asyncio.Lock()
        # Set when _ensure_page just launched a brand-new context; cleared
        # the moment _locate_prompt_box first succeeds on it. Only gates
        # which timeout _locate_prompt_box uses (see
        # COLD_START_PROMPT_BOX_WAIT_TIMEOUT_MS) — narrow on purpose, since
        # widening it to retry the whole send_prompt on any failure risks
        # re-submitting a prompt that actually went through the first time.
        self._is_fresh_context = False

    @property
    def profile_dir(self) -> Any:
        return PROFILES_DIR / self.profile_dirname

    @property
    def _auth_marker(self) -> Any:
        # Touched once send_prompt has actually completed successfully —
        # i.e. login (and any interactive challenge) is done and the saved
        # session in profile_dir is good. Its mere existence is the signal
        # _ensure_page uses to launch headless next time, since there's then
        # nothing left that needs a human to see or click.
        return self.profile_dir / ".authenticated"

    def _mark_authenticated(self) -> None:
        if not self._auth_marker.exists():
            try:
                self._auth_marker.touch()
            except OSError:
                logger.debug("Could not write auth marker for %s", self.name, exc_info=True)

    async def _ensure_page(self, *, force_headed: bool = False) -> Any:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright is not installed. Install it with: "
                "pip install playwright && playwright install chromium"
            ) from exc

        if self._context is None:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self._playwright = await async_playwright().start()
            # Tried running headless once send_prompt had ever succeeded
            # (self._auth_marker) to eliminate the window entirely instead of
            # just hiding it — confirmed on Gemini specifically that it
            # detects and blocks headless Chromium even with a fully valid,
            # already-authenticated session (prompt box never renders), so
            # that's opt-in only now via ASSISTANT_AI_BRIDGE_TRY_HEADLESS=1,
            # in case that ever changes or doesn't apply to some other
            # provider. force_headed=True (from reveal()) always launches
            # headed regardless, for re-logging in after a session expires.
            try_headless_env = os.environ.get("ASSISTANT_AI_BRIDGE_TRY_HEADLESS") == "1"
            headless = not force_headed and try_headless_env and self._auth_marker.exists()
            self._headless = headless

            launch_kwargs: dict[str, Any] = {
                "user_data_dir": str(self.profile_dir),
                "headless": headless,
            }
            on_virtual_display = False
            if not headless:
                launch_kwargs["args"] = ["--window-size=480,360"]
                if not force_headed:
                    # Real headed rendering (Gemini requires it) without it
                    # ever touching the user's actual screen: point the
                    # browser subprocess at a hidden Xvfb display instead of
                    # the real one. A window that's launched on the real
                    # display but merely minimized/unfocused was confirmed
                    # the hard way to fail the same way headless does —
                    # Gemini's page never finishes rendering — so Xvfb (a
                    # real, focused compositor the browser is never aware is
                    # invisible to the user) is what actually solves both
                    # problems at once.
                    display = await virtual_display.get_display()
                    if display is not None:
                        launch_kwargs["env"] = {**os.environ, "DISPLAY": display}
                        on_virtual_display = True
                    else:
                        # Xvfb unavailable — fall back to the old best-effort
                        # minimized-on-the-real-display hint.
                        launch_kwargs["args"] = ["--start-minimized", "--window-size=480,360"]
            self._on_virtual_display = on_virtual_display

            self._context = await self._playwright.chromium.launch_persistent_context(**launch_kwargs)
            self._is_fresh_context = True
            logger.info(
                "Launched persistent %s browser context (headless=%s, virtual_display=%s) at %s",
                self.name,
                headless,
                on_virtual_display,
                self.profile_dir,
            )

        if self._page is None or self._page.is_closed():
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()

        if self.url not in self._page.url:
            await self._page.goto(self.url, wait_until="domcontentloaded")

        return self._page

    async def open(self, *, reveal: bool = False) -> Any:
        async with self._lock:
            page = await self._ensure_page()
        if reveal:
            await self.reveal()
        return page

    async def _set_window_bounds(self, bounds: dict[str, Any]) -> None:
        # CDP, not a Playwright-native API: Playwright has no cross-platform
        # "move/minimize window" call, and --start-minimized alone is
        # unreliably honored by some Linux window managers. Best-effort —
        # some window managers ignore CDP window-state requests too, but this
        # is what actually keeps the automated browser out of sight in
        # practice, without moving it off-screen (which stopped some of these
        # sites, Gemini in particular, from finishing their own rendering).
        if self._page is None or self._context is None:
            return
        try:
            cdp = await self._context.new_cdp_session(self._page)
            window = await cdp.send("Browser.getWindowForTarget")
            await cdp.send("Browser.setWindowBounds", {"windowId": window["windowId"], "bounds": bounds})
        except Exception:
            logger.debug("Could not set window bounds for %s", self.name, exc_info=True)

    async def reveal(self) -> None:
        if self._context is None or self._headless or self._on_virtual_display:
            # No on-screen window to reveal yet (never opened), the current
            # context is headless (nothing to reveal, by definition — e.g.
            # the saved session just expired and re-login is needed), or
            # it's rendering on the hidden Xvfb display, which the user's
            # real screen can't show regardless of window state. In every
            # case, tear down and relaunch headed on the real display —
            # _ensure_page's own logic would otherwise just relaunch back
            # onto Xvfb or headless.
            async with self._lock:
                if self._context is not None:
                    await self._context.close()
                    self._context = None
                    self._page = None
                await self._ensure_page(force_headed=True)

        if self._page is not None:
            # windowState must be restored to "normal" in its own call before
            # bounds can be changed — Chrome's CDP rejects setting size/
            # position together with a state change out of "minimized" in one call.
            await self._set_window_bounds({"windowState": "normal"})
            await self._set_window_bounds({"left": 80, "top": 80, "width": 1280, "height": 800})
            await self._page.bring_to_front()

    async def hide(self) -> None:
        """Explicit, user-triggered only (never automatic): tears down
        whatever's currently on the real screen (from a prior reveal()) and
        relaunches back onto the hidden Xvfb display, so the window is
        actually gone rather than merely minimized — some window managers
        ignore a minimize request outright, which would leave it fully
        visible, and Playwright's own visibility checks fail on a minimized
        window anyway for the next fill()/click()."""
        async with self._lock:
            if self._context is not None:
                await self._context.close()
                self._context = None
                self._page = None
            await self._ensure_page()

    async def close(self) -> None:
        async with self._lock:
            if self._context is not None:
                try:
                    await self._context.close()
                except Exception as context_already_gone:
                    logger.debug(
                        "Error closing %s browser context: %s", self.name, context_already_gone, exc_info=True
                    )
                finally:
                    self._context = None
                    self._page = None
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception as driver_already_stopped:
                    logger.debug(
                        "Error stopping %s playwright driver: %s", self.name, driver_already_stopped, exc_info=True
                    )
                finally:
                    self._playwright = None
            logger.info("Closed %s browser context.", self.name)

    async def _locate_prompt_box(self, page: Any) -> Any:
        """Waits for one of prompt_box_selectors to actually appear, rather
        than checking Locator.count() immediately (which doesn't wait and
        was the real cause of "works on retry, fails on the very first
        query after startup" — right after a fresh navigation the SPA has
        only reached domcontentloaded, not finished hydrating, so the box
        genuinely isn't in the DOM yet for an instant; the same race can
        happen for a moment right after the previous reply finishes
        rendering too)."""
        timeout_ms = COLD_START_PROMPT_BOX_WAIT_TIMEOUT_MS if self._is_fresh_context else PROMPT_BOX_WAIT_TIMEOUT_MS
        last_error: Exception | None = None
        for selector in self.prompt_box_selectors:
            try:
                await page.wait_for_selector(selector, timeout=timeout_ms, state="visible")
                self._is_fresh_context = False
                return page.locator(selector).first
            except Exception as exc:
                last_error = exc
        raise RuntimeError(
            f"Could not locate the {self.name} prompt input box. The site may have "
            f"changed its layout; selectors in modules/ai_bridge/providers/ "
            "may need adjusting."
        ) from last_error

    def _response_block_locators(self, page: Any) -> Any:
        for selector in self.response_block_selectors:
            yield selector, page.locator(selector)

    async def _find_working_response_locator(self, page: Any) -> Any:
        for _selector, locator in self._response_block_locators(page):
            if await locator.count() > 0:
                return locator
        return None

    async def _submit(self, page: Any, prompt_box: Any) -> None:
        send_button = page.get_by_role("button", name=re.compile("send", re.I))
        if await send_button.count() > 0 and await send_button.first.is_enabled():
            await send_button.first.click()
        else:
            await prompt_box.press("Enter")

    async def _ensure_fast_mode(self, page: Any) -> None:
        """Best-effort hook: switch the provider's UI to its fastest model/mode
        before sending a prompt. Swallow failures — this is an optimization,
        never a hard requirement to send the prompt."""
        return None

    async def _wait_for_response(self, page: Any, previous_count: int) -> str:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + RESPONSE_WAIT_TIMEOUT_SECONDS

        locator = None
        while loop.time() < deadline:
            locator = await self._find_working_response_locator(page)
            if locator is not None and await locator.count() > previous_count:
                break
            await asyncio.sleep(RESPONSE_POLL_INTERVAL_SECONDS)
        else:
            raise RuntimeError(
                f"Timed out waiting for a {self.name} response to appear. The site may "
                "have changed its layout; selectors in modules/ai_bridge/providers/ "
                "may need adjusting."
            )

        assert locator is not None
        last_text = None
        stable_reads = 0
        while loop.time() < deadline:
            current_text = await locator.last.inner_text()
            if current_text == last_text:
                stable_reads += 1
                if stable_reads >= RESPONSE_STABLE_READS_REQUIRED:
                    return current_text
            else:
                stable_reads = 0
            last_text = current_text
            await asyncio.sleep(RESPONSE_POLL_INTERVAL_SECONDS)

        raise RuntimeError(
            f"Timed out waiting for the {self.name} response to finish streaming. "
            f"Response did not stabilize within {RESPONSE_WAIT_TIMEOUT_SECONDS}s."
        )

    async def send_prompt(self, text: str, *, fast_mode: bool = False) -> str:
        async with self._lock:
            page = await self._ensure_page()

            if fast_mode:
                try:
                    await self._ensure_fast_mode(page)
                except Exception as exc:
                    logger.debug("Could not switch %s to fast mode: %s", self.name, exc)

            prompt_box = await self._locate_prompt_box(page)
            await prompt_box.click()
            await prompt_box.fill(text)

            existing_locator = await self._find_working_response_locator(page)
            previous_count = await existing_locator.count() if existing_locator is not None else 0

            await self._submit(page, prompt_box)

            response_text = await self._wait_for_response(page, previous_count)
            logger.info("Received %s response (%d chars)", self.name, len(response_text))
            self._mark_authenticated()
            return response_text

    async def is_limit_reached(self) -> bool:
        if not self.limit_markers:
            return False
        async with self._lock:
            page = await self._ensure_page()
        try:
            body_text = (await page.locator("body").inner_text()).lower()
        except Exception as exc:
            logger.debug("Could not read %s page text to check limit status: %s", self.name, exc)
            return False
        return any(marker.lower() in body_text for marker in self.limit_markers)

    async def is_logged_in(self) -> bool:
        """Never opens a browser just to check — status is only meaningful
        for a provider whose session is already open (see
        provider_auth.py); an unopened context honestly reports "guest"
        rather than launching a whole browser for a status check."""
        if self._context is None:
            return False
        async with self._lock:
            page = await self._ensure_page()
        try:
            body_text = (await page.locator("body").inner_text()).lower()
        except Exception as exc:
            logger.debug("Could not read %s page text to check login status: %s", self.name, exc)
            return False
        return not any(marker in body_text for marker in self.guest_markers)

    @abstractmethod
    def _describe(self) -> str:
        """Subclasses must exist as distinct, named provider adapters."""
        raise NotImplementedError
