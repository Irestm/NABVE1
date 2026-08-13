from __future__ import annotations

from types import ModuleType


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


def click(x: int, y: int, button: str = "left") -> None:
    pyautogui = _require_pyautogui()
    pyautogui.click(x=x, y=y, button=button)


def move_mouse(x: int, y: int) -> None:
    pyautogui = _require_pyautogui()
    pyautogui.moveTo(x, y)


def type_text(text: str) -> None:
    pyautogui = _require_pyautogui()
    pyautogui.typewrite(text)


def press_key(key: str) -> None:
    pyautogui = _require_pyautogui()
    pyautogui.press(key)
