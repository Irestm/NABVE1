from __future__ import annotations

from dataclasses import dataclass

# Actions the grounding step (see grounding.py) can resolve a voice
# instruction into. Kept as a small closed set on purpose — the model picks
# one of these three per step, it never invents a new action kind.
ACTIONS = ("click", "type_text", "press_key")


@dataclass(frozen=True)
class UIElement:
    """One interactive element from the active application's accessibility
    tree, already filtered down to something worth offering the grounding
    model as a click target — see atspi_adapter.py."""

    index: int  # position in the list handed to the grounding prompt; the
    # model picks an element *by this index*, not by matching its name back
    # as a string — mirrors modules.app_catalog.resolver's index-based pick.
    role: str  # AT-SPI role name, e.g. "push button", "menu item", "text"
    name: str  # accessible name/label, e.g. "Сохранить"
    bbox: tuple[int, int, int, int]  # x, y, width, height — absolute screen
    # pixels, the same coordinate space core/os_adapter/screen.py already
    # clicks in.


@dataclass(frozen=True)
class UIStep:
    """One resolved action to execute. `element` is set only for "click";
    `text`/`key` only for "type_text"/"press_key" respectively — enforced by
    grounding._parse_grounding, not by this dataclass itself."""

    action: str
    element: UIElement | None = None
    text: str | None = None
    key: str | None = None
