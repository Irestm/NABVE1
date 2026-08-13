from __future__ import annotations

import asyncio
import os
from typing import Any

from core.logger import get_logger
from core.os_adapter.base import ActiveWindow
from modules.ui_automation.domain import UIElement

logger = get_logger(__name__)

_DEFAULT_PORT = "9222"

# Chrome/Chromium appends one of these after the page's own title in the OS
# window title — stripped for comparison against a Playwright Page's own
# title() when looking for the tab that matches the OS-focused window.
# Heuristic, not a hard identifier (see _find_page).
_TITLE_SUFFIXES = (" - Google Chrome", " - Chromium", " - Chromium Web Browser")

_INTERACTIVE_SELECTOR = (
    "button, a[href], input:not([type=hidden]), textarea, select, "
    "[role=button], [role=link], [role=tab], [role=checkbox], [role=radio], [role=combobox], "
    "[onclick]"
)

# A hard cap, same purpose as atspi_adapter.py's _MAX_ELEMENTS — keeps the
# eventual grounding prompt's token budget sane on a content-heavy page.
_MAX_ELEMENTS = 200

_ARIA_ROLE_MAP = {
    "button": "push button",
    "link": "link",
    "tab": "page tab",
    "checkbox": "check box",
    "radio": "radio button",
    "combobox": "combo box",
}
_INPUT_TYPE_MAP = {"checkbox": "check box", "radio": "radio button"}


def _cdp_port() -> str:
    return os.environ.get("ASSISTANT_CHROME_CDP_PORT", _DEFAULT_PORT)


def _strip_title_suffix(title: str) -> str:
    for suffix in _TITLE_SUFFIXES:
        if title.endswith(suffix):
            return title[: -len(suffix)]
    return title


def normalize_role(tag: str, input_type: str, aria_role: str | None) -> str:
    """Maps an HTML tag/ARIA role onto the exact same role vocabulary
    AT-SPI already produces (see modules.ui_automation.domain.UIElement's
    docstring) and modules.ui_automation.announce already has phrasing for
    — so announce.py needs zero changes regardless of which inspector
    produced a given element."""
    if aria_role and aria_role in _ARIA_ROLE_MAP:
        return _ARIA_ROLE_MAP[aria_role]
    if tag == "a":
        return "link"
    if tag == "select":
        return "combo box"
    if tag == "textarea":
        return "entry"
    if tag == "input":
        return _INPUT_TYPE_MAP.get(input_type, "entry")
    return "push button"  # <button>, [onclick], or an unrecognized aria role


def to_absolute_bbox(
    *,
    window_left: float,
    window_top: float,
    chrome_offset_x: float,
    chrome_offset_y: float,
    device_pixel_ratio: float,
    el_x: float,
    el_y: float,
    el_width: float,
    el_height: float,
) -> tuple[int, int, int, int]:
    """Translates a DOM element's viewport-relative CSS-pixel bounding box
    into absolute physical screen pixels — the same coordinate space
    AT-SPI's UIElement.bbox already uses, so nothing downstream (
    service_layer.to_command_params, modules.ui_automation.handlers) needs
    to know or care which inspector produced a given element.

    `getBoundingClientRect()` is in CSS pixels; the window position from CDP
    (`Browser.getWindowBounds`) is in physical/device pixels. On any HiDPI
    display (`devicePixelRatio != 1` — most laptop panels today), skipping
    the multiply below makes every click land at the wrong spot by exactly
    that factor — this is not optional. Browser zoom level is a separate,
    harder problem (not corrected for here)."""
    x = window_left + device_pixel_ratio * (chrome_offset_x + el_x)
    y = window_top + device_pixel_ratio * (chrome_offset_y + el_y)
    width = device_pixel_ratio * el_width
    height = device_pixel_ratio * el_height
    return (round(x), round(y), round(width), round(height))


class ChromeCdpElementInspector:
    """Adapter satisfying modules.ui_automation.ports.ElementInspectorPort
    by attaching, via Playwright, to an ALREADY-RUNNING Chrome/Chromium the
    user must launch themselves with `--remote-debugging-port=<port>` (port
    from ASSISTANT_CHROME_CDP_PORT, default 9222) — Chrome cannot have a
    debug port attached retroactively to an instance that wasn't started
    with the flag, so this is a real, unavoidable manual setup step (same
    class of requirement as AT-SPI's accessibility toggles in
    atspi_adapter.py). `playwright` is imported lazily inside
    list_elements, same reasoning as atspi_adapter.py's _require_atspi():
    importing this module must never hard-fail just because Chrome isn't
    running with the flag right now — any failure here (connection
    refused, no matching tab, ...) degrades to an empty list, which
    modules.ui_automation.service_layer treats as "try AT-SPI instead"."""

    def list_elements(self, active: ActiveWindow) -> list[UIElement]:
        try:
            return asyncio.run(self._list_elements_async(active))
        except Exception:
            logger.info("Chrome CDP element listing unavailable", exc_info=True)
            return []

    async def _list_elements_async(self, active: ActiveWindow) -> list[UIElement]:
        from playwright.async_api import async_playwright

        target_title = _strip_title_suffix(active.title)

        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(f"http://localhost:{_cdp_port()}")
            try:
                page = await self._find_page(browser, target_title)
                if page is None:
                    logger.info("No open Chrome tab matched active window title %r", active.title)
                    return []
                return await self._extract_elements(page)
            finally:
                await browser.close()

    @staticmethod
    async def _find_page(browser: Any, target_title: str) -> Any | None:
        for context in browser.contexts:
            for page in context.pages:
                try:
                    title = await page.title()
                except Exception:
                    continue
                if title == target_title:
                    return page
                # str.startswith("") is always True, so this branch must
                # never run when either title is empty — a still-loading
                # tab, about:blank, or a titleless devtools/background page
                # would otherwise match ANY active window title and get
                # picked over the real match.
                if title and target_title and (target_title.startswith(title) or title.startswith(target_title)):
                    return page
        return None

    @staticmethod
    async def _extract_elements(page: Any) -> list[UIElement]:
        raw_elements = await page.eval_on_selector_all(
            _INTERACTIVE_SELECTOR,
            """
            (elements) => elements.map(el => {
                const rect = el.getBoundingClientRect();
                return {
                    tag: el.tagName.toLowerCase(),
                    type: (el.getAttribute('type') || '').toLowerCase(),
                    role: el.getAttribute('role'),
                    name: (el.getAttribute('aria-label') || el.innerText || el.value
                           || el.placeholder || '').trim().slice(0, 120),
                    x: rect.x, y: rect.y, width: rect.width, height: rect.height,
                    visible: rect.width > 0 && rect.height > 0,
                };
            })
            """,
        )
        viewport_info = await page.evaluate(
            "() => ({outerWidth: window.outerWidth, outerHeight: window.outerHeight, "
            "innerWidth: window.innerWidth, innerHeight: window.innerHeight, "
            "devicePixelRatio: window.devicePixelRatio})"
        )

        window_left, window_top = 0.0, 0.0
        try:
            cdp = await page.context.new_cdp_session(page)
            window_info = await cdp.send("Browser.getWindowForTarget")
            bounds = await cdp.send("Browser.getWindowBounds", {"windowId": window_info["windowId"]})
            window_left = float(bounds["bounds"].get("left", 0))
            window_top = float(bounds["bounds"].get("top", 0))
        except Exception:
            logger.debug("Could not read Chrome window bounds via CDP; assuming (0, 0)", exc_info=True)

        chrome_offset_y = max(0.0, viewport_info["outerHeight"] - viewport_info["innerHeight"])
        device_pixel_ratio = float(viewport_info.get("devicePixelRatio") or 1.0)

        elements: list[UIElement] = []
        for raw in raw_elements:
            if not raw.get("visible") or not raw.get("name"):
                continue
            role = normalize_role(raw["tag"], raw["type"], raw.get("role"))
            bbox = to_absolute_bbox(
                window_left=window_left,
                window_top=window_top,
                chrome_offset_x=0.0,
                chrome_offset_y=chrome_offset_y,
                device_pixel_ratio=device_pixel_ratio,
                el_x=raw["x"],
                el_y=raw["y"],
                el_width=raw["width"],
                el_height=raw["height"],
            )
            elements.append(UIElement(index=len(elements), role=role, name=raw["name"], bbox=bbox))
            if len(elements) >= _MAX_ELEMENTS:
                break

        return elements
