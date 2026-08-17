from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from core.config import DATA_DIR
from core.logger import get_logger
from modules.wordpress_bridge.domain import DraftContent, DraftResult

logger = get_logger(__name__)

PROFILES_DIR = DATA_DIR / "wordpress_profiles"

LOGIN_WAIT_TIMEOUT_MS = 300_000  # up to 5 minutes for the user to type their password
FIELD_WAIT_TIMEOUT_MS = 20_000

# WordPress core admin selectors — stable across recent WP versions (block
# editor / Gutenberg), unlike the ai_bridge providers' selectors which chase
# each vendor's own frequently-changing chat UI. Kept as module constants
# (not per-site config) since these come from WordPress itself, not from any
# individual site's theme.
_TITLE_SELECTOR = ".editor-post-title__input, #title"
_MORE_MENU_SELECTOR = 'button[aria-label="Options"]'
_CODE_EDITOR_MENU_ITEM = 'text="Code editor"'
_HTML_TEXTAREA_SELECTOR = ".editor-post-text-editor"
_SAVE_DRAFT_SELECTOR = 'button:has-text("Save draft")'
_ADMIN_BAR_SELECTOR = "#wpadminbar"
_FEATURED_IMAGE_PANEL_BUTTON = 'text="Set featured image"'
_MEDIA_UPLOAD_TAB = 'button:has-text("Upload files")'
_MEDIA_FILE_INPUT = 'input[type="file"]'
_MEDIA_SELECT_BUTTON = 'button:has-text("Set featured image")'


def _profile_dir_for(site_url: str) -> Path:
    digest = hashlib.sha256(site_url.encode("utf-8")).hexdigest()[:16]
    host = re.sub(r"[^a-z0-9]+", "_", urlparse(site_url).netloc.lower()).strip("_") or "site"
    return PROFILES_DIR / f"{host}_{digest}"


class WordPressSession:
    """One persistent, ALWAYS-VISIBLE Playwright browser session per WP
    site — deliberately not sharing modules.ai_bridge.providers.base's
    hidden-Xvfb-by-default machinery: the whole point of this module is
    that the user watches Jarvis fill in the draft in real time, so this
    never launches on a virtual display, only the real screen.

    Never automates the "Publish" button — no selector or code path for it
    exists anywhere in this class. Only publish_draft() (-> Save draft)."""

    def __init__(self, site_url: str) -> None:
        self.site_url = site_url.rstrip("/")
        self.profile_dir = _profile_dir_for(self.site_url)
        self._playwright: Any = None
        self._context: Any = None
        self._page: Any = None

    async def _ensure_page(self) -> Any:
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
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=False,
                args=["--window-size=1280,900"],
            )
            logger.info("Launched visible WordPress admin session for %s at %s", self.site_url, self.profile_dir)

        if self._page is None or self._page.is_closed():
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        return self._page

    async def _ensure_logged_in(self) -> None:
        page = await self._ensure_page()
        await page.goto(urljoin(self.site_url + "/", "wp-admin/"), wait_until="domcontentloaded")
        try:
            await page.wait_for_selector(_ADMIN_BAR_SELECTOR, timeout=3_000, state="visible")
            return  # already logged in — persisted session from a previous run
        except Exception as not_yet_logged_in:
            logger.debug(
                "No persisted WordPress session for %s yet: %s", self.site_url, not_yet_logged_in, exc_info=True
            )

        # Not logged in (or session expired): the window is already visible
        # (never launched headless), so the user can type their WordPress
        # password themselves right now — Jarvis never asks for or stores
        # it. Same principle as the AI-provider login flow.
        logger.info("Waiting for the user to log in to WordPress admin manually at %s", self.site_url)
        await page.wait_for_selector(_ADMIN_BAR_SELECTOR, timeout=LOGIN_WAIT_TIMEOUT_MS, state="visible")

    async def publish_draft(self, content: DraftContent) -> DraftResult:
        await self._ensure_logged_in()
        page = self._page

        await page.goto(urljoin(self.site_url + "/", "wp-admin/post-new.php"), wait_until="domcontentloaded")
        await page.wait_for_selector(_TITLE_SELECTOR, timeout=FIELD_WAIT_TIMEOUT_MS, state="visible")
        await page.locator(_TITLE_SELECTOR).first.fill(content.title)

        await self._paste_html_body(page, content.html_body)

        if content.featured_image_path:
            await self._set_featured_image(page, content.featured_image_path)

        await page.locator(_SAVE_DRAFT_SELECTOR).first.click()
        # Gutenberg's own "Draft saved" status text shows up in the same
        # region the Save-draft button was in — waiting for the button to
        # go back to enabled (it disables mid-save) is the reliable signal.
        await page.wait_for_selector(_SAVE_DRAFT_SELECTOR + ":not([aria-disabled='true'])", timeout=FIELD_WAIT_TIMEOUT_MS)

        edit_url = page.url
        logger.info("WordPress draft ready for review at %s (never auto-published)", edit_url)
        return DraftResult(edit_url=edit_url, title=content.title)

    async def _paste_html_body(self, page: Any, html_body: str) -> None:
        """Switches the block editor to its raw "Code editor" mode and
        pastes the whole HTML body in one shot — far more reliable to
        automate than building up individual Gutenberg blocks one at a
        time, and the user can freely re-switch to the visual editor
        themselves afterwards before publishing."""
        await page.locator(_MORE_MENU_SELECTOR).first.click()
        await page.locator(_CODE_EDITOR_MENU_ITEM).first.click()
        await page.wait_for_selector(_HTML_TEXTAREA_SELECTOR, timeout=FIELD_WAIT_TIMEOUT_MS, state="visible")
        textarea = page.locator(_HTML_TEXTAREA_SELECTOR).first
        await textarea.fill(html_body)
        # Switch back to the visual editor so the draft looks normal (with
        # images rendered etc.) the next time the user opens it.
        await page.locator(_MORE_MENU_SELECTOR).first.click()
        await page.locator('text="Visual editor"').first.click()

    async def _set_featured_image(self, page: Any, image_path: str) -> None:
        await page.locator(_FEATURED_IMAGE_PANEL_BUTTON).first.click()
        await page.wait_for_selector(_MEDIA_UPLOAD_TAB, timeout=FIELD_WAIT_TIMEOUT_MS, state="visible")
        await page.locator(_MEDIA_UPLOAD_TAB).first.click()
        await page.locator(_MEDIA_FILE_INPUT).first.set_input_files(image_path)
        await page.wait_for_selector(_MEDIA_SELECT_BUTTON, timeout=FIELD_WAIT_TIMEOUT_MS, state="visible")
        await page.locator(_MEDIA_SELECT_BUTTON).first.click()

    async def close(self) -> None:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception as context_already_gone:
                logger.debug(
                    "Error closing WordPress session context for %s: %s",
                    self.site_url,
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
                    "Error stopping WordPress playwright driver for %s: %s",
                    self.site_url,
                    driver_already_stopped,
                    exc_info=True,
                )
            finally:
                self._playwright = None


async def publish_draft(site_url: str, content: DraftContent) -> DraftResult:
    session = WordPressSession(site_url)
    try:
        return await session.publish_draft(content)
    finally:
        await session.close()
