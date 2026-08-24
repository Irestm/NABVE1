from __future__ import annotations

import asyncio
from typing import Any

from core.logger import get_logger
from core.os_adapter import get_os_adapter
from core.os_adapter.base import ActiveWindow
from modules.ui_automation import grounding
from modules.ui_automation.atspi_adapter import AtspiElementInspector
from modules.ui_automation.cdp_adapter import ChromeCdpElementInspector
from modules.ui_automation.domain import UIElement, UIStep
from modules.ui_automation.ocr_adapter import OcrElementInspector
from modules.ui_automation.ports import ElementInspectorPort

logger = get_logger(__name__)

# Module-level singletons (not constructed inline inside the routing
# function below) so tests can monkeypatch either one independently —
# mirrors modules/crm_transcribe/handlers.py's
# `_transcriber: TranscriptionPort = LocalWhisperTranscriber()`.
_atspi_inspector: ElementInspectorPort = AtspiElementInspector()
_cdp_inspector: ElementInspectorPort = ChromeCdpElementInspector()
# Last-resort fallback, tried only once AT-SPI itself came up empty — see
# _list_elements below.
_ocr_inspector: ElementInspectorPort = OcrElementInspector()

# X11 WM_CLASS values for Chromium-based browsers on Linux — used to decide
# whether it's even worth attempting a CDP connection. Not exhaustive (e.g.
# Brave/Edge/Vivaldi also ship Chromium-based, with their own wm_class) —
# unrecognized wm_class values just go straight to the AT-SPI path, same as
# any other desktop app, which is a safe default rather than a failure.
_CHROMIUM_WM_CLASSES = {
    "google-chrome",
    "google-chrome-stable",
    "google-chrome-beta",
    "google-chrome-unstable",
    "chromium",
    "chromium-browser",
    "chrome",
}


def _looks_like_chromium(active: ActiveWindow) -> bool:
    return bool(active.wm_class) and active.wm_class.lower() in _CHROMIUM_WM_CLASSES


async def _list_elements(active: ActiveWindow) -> list[UIElement]:
    """Tries the CDP-based browser inspector first when the active window's
    wm_class looks like a Chromium-based browser, falling back to AT-SPI
    when that connection isn't available (Chrome not launched with
    --remote-debugging-port — see cdp_adapter.py) or turns up nothing (no
    matching tab, e.g. because the title-matching heuristic missed, or a
    page with no recognized interactive elements). If AT-SPI also comes up
    empty (no accessibility tree at all — Electron/canvas apps are the
    common case), OcrElementInspector is tried last as a vision-based
    fallback (see ocr_adapter.py) — screenshotting the window and reading
    whatever text is actually visible on screen, since there's no tree left
    to query. ChromeCdpElementInspector and OcrElementInspector both catch
    their own errors and return [] rather than raising, so only AT-SPI's own
    exceptions (if any) propagate out of this function — left for
    ground_instruction's existing try/except to handle, same as before this
    routing existed."""
    if _looks_like_chromium(active):
        elements = await asyncio.to_thread(_cdp_inspector.list_elements, active)
        if elements:
            return elements

    elements = await asyncio.to_thread(_atspi_inspector.list_elements, active)
    if elements:
        return elements

    return await asyncio.to_thread(_ocr_inspector.list_elements, active)


async def list_active_elements(active: ActiveWindow) -> list[UIElement]:
    """Public wrapper around _list_elements — the same CDP/AT-SPI/OCR
    routing ground_instruction uses below, exposed for
    modules.os_agent.runner's own observe step so it doesn't duplicate the
    inspector-selection logic."""
    return await _list_elements(active)


async def ground_instruction(raw_text: str) -> list[UIStep] | None:
    """Resolves a free-text UI instruction against whatever application
    currently has OS focus. Returns None on any failure along the way — no
    active window, no working element inspector for it (AT-SPI not
    installed / bus down / the app doesn't expose a tree; CDP unreachable
    and AT-SPI also came up empty; and now the OCR fallback also found no
    readable text), or the grounding model couldn't confidently match
    anything — all of which degrade the same way for the caller: an
    ordinary "не поняла команду", never a crash."""
    raw_text = raw_text.strip()
    if not raw_text:
        return None

    adapter = get_os_adapter()
    try:
        active = await asyncio.to_thread(adapter.get_active_window)
    except Exception:
        logger.exception("get_active_window failed")
        return None
    if active is None:
        return None

    try:
        elements = await _list_elements(active)
    except Exception:
        logger.exception("Listing UI elements failed")
        return None
    if not elements:
        return None

    return await grounding.ground(active.title, elements, raw_text)


def to_command_params(steps: list[UIStep]) -> list[dict[str, Any]]:
    """Flattens UIStep/UIElement into the plain-primitive dicts the
    dispatcher's ui_action handler needs (and that CommandResponse can
    JSON-serialize) — the bbox center for a click, text/key verbatim
    otherwise. Coordinates are already absolute screen pixels regardless of
    which inspector produced the element (see cdp_adapter.to_absolute_bbox),
    so this needs no knowledge of AT-SPI vs CDP."""
    params: list[dict[str, Any]] = []
    for step in steps:
        if step.action == "click":
            assert step.element is not None
            x, y, w, h = step.element.bbox
            params.append({"action": "click", "x": x + w // 2, "y": y + h // 2, "button": "left"})
        elif step.action == "type_text":
            params.append({"action": "type_text", "text": step.text})
        else:
            params.append({"action": "press_key", "key": step.key})
    return params
