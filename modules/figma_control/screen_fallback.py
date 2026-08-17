from __future__ import annotations

from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from core.logger import get_logger
from core.os_adapter import get_os_adapter
from core.os_adapter.screenshot import capture_window

logger = get_logger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# cv2.matchTemplate's TM_CCOEFF_NORMED score (-1..1) above which a found
# icon is trusted enough to click. Conservative on purpose: a false
# positive here means clicking the wrong Figma tool/button, not just
# failing silently like a too-low OCR confidence would.
_TEMPLATE_MATCH_CONFIDENCE = 0.85

_DRAG_DURATION_SECONDS = 0.15


class FigmaNotFocusedError(Exception):
    """Raised whenever a fallback sequence would otherwise click/type
    blindly into whatever window happens to be focused. Per the task's
    security note: never assume the active window is Figma just because
    the user asked for a Figma action — modules/figma_control/dispatcher.py
    turns this into a spoken refusal instead of proceeding."""


class FallbackActionUnsupportedError(Exception):
    """Raised when neither a keyboard shortcut nor a located screen element
    can carry out an action reliably enough to attempt it. The dispatcher
    turns this into the "can't do that in Figma" spoken response the task
    asks for, rather than guessing with a blind coordinate click."""


def _require_pyautogui() -> ModuleType:
    try:
        import tkinter  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "GUI automation requires tkinter. Install it with: "
            "sudo apt-get install python3-tk python3-dev (Linux) "
            "or reinstall Python with tcl/tk support (Windows)."
        ) from exc

    import pyautogui

    return pyautogui


def _require_cv2() -> ModuleType:
    try:
        import cv2  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "Icon-based fallback requires OpenCV. Install it with: pip install opencv-python-headless"
        ) from exc
    return cv2


def ensure_figma_focused() -> None:
    """Must be called before any fallback sequence that clicks or types.
    See this module's docstring and the task's security note: a
    click-based fallback firing at whatever window happens to be focused
    (not necessarily Figma) could hit anything."""
    adapter = get_os_adapter()
    active = adapter.get_active_window()
    if active is None:
        raise FigmaNotFocusedError("Could not determine the active window")
    if "figma" not in active.title.lower():
        raise FigmaNotFocusedError(f"Active window is '{active.title}', not Figma")


def find_icon_on_screen(
    template_name: str, *, confidence: float = _TEMPLATE_MATCH_CONFIDENCE
) -> tuple[int, int] | None:
    """Locates a Figma UI icon (toolbar tool, alignment button, ...) inside
    the current Figma window via OpenCV template matching against a
    reference crop, instead of a hardcoded coordinate — a fixed (x, y)
    breaks across screen resolutions, OS display scaling, and Figma UI
    layout changes; a template crop of the icon itself doesn't. Returns the
    icon's absolute screen center, or None if it isn't visible right now
    (wrong panel/tab open, template captured at a different scale, etc.) —
    never a guess.

    Reference crops live in modules/figma_control/templates/<template_name>
    and are NOT bundled — this repo can't ship real Figma UI screenshots.
    See that directory's README for how to capture your own.
    """
    cv2 = _require_cv2()
    import numpy as np

    template_path = TEMPLATES_DIR / template_name
    if not template_path.is_file():
        logger.warning("Icon template not found: %s", template_path)
        return None

    adapter = get_os_adapter()
    active = adapter.get_active_window()
    if active is None:
        return None

    screenshot, (offset_x, offset_y) = capture_window(active)
    haystack = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
    needle = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
    if needle is None:
        logger.warning("Icon template could not be read: %s", template_path)
        return None

    result = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < confidence:
        return None

    needle_height, needle_width = needle.shape[:2]
    return offset_x + max_loc[0] + needle_width // 2, offset_y + max_loc[1] + needle_height // 2


def _find_text_on_screen(word: str) -> tuple[int, int] | None:
    """Same "find it on screen, don't hardcode a coordinate" principle as
    find_icon_on_screen, but for text (layer names in the layers panel)
    rather than icons — reuses modules/ui_automation's existing OCR
    fallback (pytesseract) instead of a second OCR integration."""
    from modules.ui_automation.ocr_adapter import OcrElementInspector

    adapter = get_os_adapter()
    active = adapter.get_active_window()
    if active is None:
        return None

    normalized = word.strip().lower()
    for element in OcrElementInspector().list_elements(active):
        if element.name.strip().lower() == normalized:
            x, y, width, height = element.bbox
            return x + width // 2, y + height // 2
    return None


def _drag(pyautogui: ModuleType, start: tuple[int, int], width: int, height: int) -> None:
    x, y = start
    pyautogui.moveTo(x, y)
    pyautogui.mouseDown()
    pyautogui.moveTo(x + width, y + height, duration=_DRAG_DURATION_SECONDS)
    pyautogui.mouseUp()


def _viewport_center() -> tuple[int, int]:
    adapter = get_os_adapter()
    active = adapter.get_active_window()
    if active is not None and active.bbox is not None:
        x, y, width, height = active.bbox
        return x + width // 2, y + height // 2
    pyautogui = _require_pyautogui()
    size = pyautogui.size()
    return size[0] // 2, size[1] // 2


# ---- per-action fallbacks --------------------------------------------
#
# Only actions this module can carry out honestly are registered in
# _ACTIONS below — see execute()'s docstring. Real, resolution-independent
# global keyboard shortcuts (Figma's default tool/edit shortcuts) are
# preferred wherever they exist; everything else goes through
# find_icon_on_screen/_find_text_on_screen rather than a fixed coordinate.
# move_layer/resize_layer/change_color/export_selection have no reliable
# fallback (they need precise numeric-field entry in Figma's right panel,
# which OCR/template matching can't target safely) and are deliberately
# left unimplemented — execute() reports those as unsupported rather than
# risk typing into the wrong field.


def create_rectangle(params: dict[str, Any]) -> str:
    ensure_figma_focused()
    pyautogui = _require_pyautogui()
    width, height = int(params.get("width", 100)), int(params.get("height", 100))
    pyautogui.press("r")
    _drag(pyautogui, _viewport_center(), width, height)
    pyautogui.press("escape")
    return "Прямоугольник создан через управление экраном."


def create_frame(params: dict[str, Any]) -> str:
    ensure_figma_focused()
    pyautogui = _require_pyautogui()
    width, height = int(params.get("width", 100)), int(params.get("height", 100))
    pyautogui.press("f")
    _drag(pyautogui, _viewport_center(), width, height)
    pyautogui.press("escape")
    return "Фрейм создан через управление экраном."


def create_text(params: dict[str, Any]) -> str:
    content = params.get("content")
    if not content:
        raise FallbackActionUnsupportedError("Missing 'content' for create_text")
    ensure_figma_focused()
    pyautogui = _require_pyautogui()
    pyautogui.press("t")
    x, y = _viewport_center()
    pyautogui.click(x=x, y=y)
    pyautogui.typewrite(str(content))
    pyautogui.press("escape")
    return "Текст создан через управление экраном."


def select_layer(params: dict[str, Any]) -> str:
    layer_name = params.get("layer_name")
    if not layer_name:
        raise FallbackActionUnsupportedError("Missing 'layer_name' for select_layer")
    ensure_figma_focused()
    location = _find_text_on_screen(str(layer_name).split()[0])
    if location is None:
        raise FallbackActionUnsupportedError(
            f"Could not locate layer '{layer_name}' on screen (it may be scrolled out of the layers panel)"
        )
    pyautogui = _require_pyautogui()
    pyautogui.click(x=location[0], y=location[1])
    return f"Слой «{layer_name}» выделен через управление экраном."


def group_selection(_params: dict[str, Any]) -> str:
    ensure_figma_focused()
    pyautogui = _require_pyautogui()
    pyautogui.hotkey("ctrl", "g")
    return "Слои сгруппированы через управление экраном."


def delete_layer(_params: dict[str, Any]) -> str:
    # No safe, resolution-independent way to select a layer purely by name
    # from the screen beyond select_layer's OCR best-effort above — this
    # only deletes whatever is already selected (e.g. right after a
    # select_layer that just ran, via either execution path).
    ensure_figma_focused()
    pyautogui = _require_pyautogui()
    pyautogui.press("delete")
    return "Слой удалён через управление экраном."


def undo(_params: dict[str, Any]) -> str:
    ensure_figma_focused()
    pyautogui = _require_pyautogui()
    pyautogui.hotkey("ctrl", "z")
    return "Отменено через управление экраном."


def redo(_params: dict[str, Any]) -> str:
    ensure_figma_focused()
    pyautogui = _require_pyautogui()
    pyautogui.hotkey("ctrl", "shift", "z")
    return "Повторено через управление экраном."


_ALIGN_TEMPLATES: dict[str, str] = {
    "left": "align_left.png",
    "right": "align_right.png",
    "center_horizontal": "align_center_horizontal.png",
    "center_vertical": "align_center_vertical.png",
    "top": "align_top.png",
    "bottom": "align_bottom.png",
}


def align(params: dict[str, Any]) -> str:
    ensure_figma_focused()
    alignment = str(params.get("alignment", ""))
    template_name = _ALIGN_TEMPLATES.get(alignment)
    if template_name is None:
        raise FallbackActionUnsupportedError(f"Unknown alignment '{alignment}'")
    location = find_icon_on_screen(template_name)
    if location is None:
        raise FallbackActionUnsupportedError(
            "Could not locate the alignment button on screen (icon template missing or not visible — "
            "the properties panel may need a layer selected first)"
        )
    pyautogui = _require_pyautogui()
    pyautogui.click(x=location[0], y=location[1])
    return "Выравнивание выполнено через управление экраном."


_ACTIONS: dict[str, Callable[[dict[str, Any]], str]] = {
    "create_rectangle": create_rectangle,
    "create_frame": create_frame,
    "create_text": create_text,
    "select_layer": select_layer,
    "group_selection": group_selection,
    "delete_layer": delete_layer,
    "align": align,
    "undo": undo,
    "redo": redo,
}


def execute(action: str, params: dict[str, Any]) -> str:
    """Entry point for modules/figma_control/dispatcher.py — used when the
    plugin isn't connected, or replied {"status": "unsupported"}. Raises
    FigmaNotFocusedError or FallbackActionUnsupportedError (never
    fabricates success) whenever `action` can't be safely/reliably carried
    out; the dispatcher turns either into the spoken "can't do that"
    response the task's security note requires, instead of clicking blind.
    Returns a human-readable (Russian) confirmation string on success."""
    handler = _ACTIONS.get(action)
    if handler is None:
        raise FallbackActionUnsupportedError(f"No screen-fallback implementation for action '{action}'")
    return handler(params)
