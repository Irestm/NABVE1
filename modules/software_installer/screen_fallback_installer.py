from __future__ import annotations

from pathlib import Path
from types import ModuleType

from core.logger import get_logger
from core.os_adapter import get_os_adapter
from core.os_adapter.screenshot import capture_window

logger = get_logger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Same TM_CCOEFF_NORMED threshold and reasoning as
# modules/figma_control/screen_fallback.py: a false positive here clicks the
# wrong button in a real installer, so stay conservative.
_TEMPLATE_MATCH_CONFIDENCE = 0.86

# One logical button, several reference crops (localized text, light/dark
# theme, different installer toolkits). Capture your own into TEMPLATES_DIR
# — none are bundled, this repo can't ship third-party installer chrome.
_BUTTON_TEMPLATES: dict[str, tuple[str, ...]] = {
    "next": ("next_en.png", "next_ru.png", "continue_en.png", "dalee_ru.png"),
    "install": ("install_en.png", "install_ru.png", "ustanovit_ru.png"),
    "finish": ("finish_en.png", "finish_ru.png", "gotovo_ru.png", "done_en.png"),
    "accept": ("accept_en.png", "agree_en.png", "prinyat_ru.png", "soglasen_ru.png"),
}

# If the active window looks like a browser (or our own assistant UI), a
# click-based "press Install" almost certainly means a web page's fake
# install button or the app itself — refuse rather than click blind. Same
# spirit as figma_control's ensure_figma_focused guard.
_REFUSE_WINDOW_MARKERS = (
    "mozilla firefox", "google chrome", "chromium", "microsoft edge", "opera", "brave",
    "safari", "vivaldi", "yandex", "assistant core", "neural assistant",
)


class InstallerButtonNotFoundError(Exception):
    """No template for the requested button matched the current screen."""


class UnsafeInstallerContextError(Exception):
    """The active window is a browser / our own UI — clicking an installer
    button there would be a blind, likely wrong click."""


def _require_cv2() -> ModuleType:
    try:
        import cv2  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "Installer screen fallback requires OpenCV. Install: pip install opencv-python-headless"
        ) from exc
    return cv2


def _require_pyautogui() -> ModuleType:
    import pyautogui

    return pyautogui


def _guard_active_window() -> str:
    adapter = get_os_adapter()
    active = adapter.get_active_window()
    if active is None:
        raise UnsafeInstallerContextError("Не удалось определить активное окно.")
    lowered = active.title.lower()
    if any(marker in lowered for marker in _REFUSE_WINDOW_MARKERS):
        raise UnsafeInstallerContextError(
            f"Активное окно «{active.title}» похоже на браузер или интерфейс ассистента, не на установщик."
        )
    return active.title


def _find_template(template_name: str, confidence: float) -> tuple[int, int] | None:
    cv2 = _require_cv2()
    import numpy as np

    template_path = TEMPLATES_DIR / template_name
    if not template_path.is_file():
        return None

    adapter = get_os_adapter()
    active = adapter.get_active_window()
    if active is None:
        return None

    screenshot, (offset_x, offset_y) = capture_window(active)
    haystack = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
    needle = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
    if needle is None:
        return None

    result = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < confidence:
        return None
    needle_height, needle_width = needle.shape[:2]
    return offset_x + max_loc[0] + needle_width // 2, offset_y + max_loc[1] + needle_height // 2


def click_installer_button(kind: str) -> str:
    """Finds and clicks the installer's <kind> button
    (next/install/finish/accept) in the currently visible installer window.
    Raises rather than guessing when the context looks unsafe or no button
    template matches."""
    templates = _BUTTON_TEMPLATES.get(kind)
    if templates is None:
        raise ValueError(f"Неизвестная кнопка установщика «{kind}».")

    window_title = _guard_active_window()

    for template_name in templates:
        location = _find_template(template_name, _TEMPLATE_MATCH_CONFIDENCE)
        if location is not None:
            _require_pyautogui().click(x=location[0], y=location[1])
            logger.info("Clicked installer '%s' button in window '%s'", kind, window_title)
            return f"Нажал «{_BUTTON_LABELS[kind]}» в установщике."

    raise InstallerButtonNotFoundError(
        f"Не вижу кнопку «{_BUTTON_LABELS[kind]}» в окне «{window_title}». "
        "Добавьте шаблон в modules/software_installer/templates или нажмите вручную."
    )


_BUTTON_LABELS: dict[str, str] = {
    "next": "Далее",
    "install": "Установить",
    "finish": "Готово",
    "accept": "Принять",
}
