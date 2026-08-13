from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.os_adapter.base import ActiveWindow
from modules.ui_automation.domain import UIElement


@runtime_checkable
class ElementInspectorPort(Protocol):
    """Anything that can enumerate the interactive elements of a running
    application, given the OS's currently-active window. Two
    implementations: AT-SPI (atspi_adapter.py, Linux desktop apps — the
    default/fallback) and CDP (cdp_adapter.py, Chromium-based browsers,
    selected by modules.ui_automation.service_layer._select_inspector based
    on ActiveWindow.wm_class). Everything downstream (grounding.py,
    service_layer.py, handlers.py) only ever talks to this Protocol and to
    UIElement/UIStep, never to AT-SPI or CDP directly — the whole point of
    the seam. Takes the full ActiveWindow (not just a bare pid) because the
    CDP adapter needs the window title to find the right browser tab, not a
    process id (Chrome is multi-process; the OS-reported pid doesn't
    identify a specific tab)."""

    def list_elements(self, active: ActiveWindow) -> list[UIElement]: ...
