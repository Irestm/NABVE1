from __future__ import annotations

import subprocess

from core.logger import get_logger
from core.os_adapter import screen
from core.os_adapter.base import ActiveWindow, OSAdapter

logger = get_logger(__name__)

# `start` exits almost immediately when it can't find a handler for
# `target` — Popen() succeeding only means cmd.exe itself launched, not that
# `start` actually opened anything. See core/os_adapter/linux.py's identical
# reasoning for xdg-open.
_OPEN_APPLICATION_GRACE_SECONDS = 0.6


class WindowsAdapter(OSAdapter):
    def open_application(self, target: str) -> bool:
        try:
            process = subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)
        except OSError as exc:
            logger.error("Failed to open application '%s': %s", target, exc)
            return False

        try:
            return_code = process.wait(timeout=_OPEN_APPLICATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            return True
        if return_code != 0:
            logger.error(
                "Application '%s' exited immediately with code %s — likely no handler or not found",
                target,
                return_code,
            )
            return False
        return True

    def close_application(self, target: str) -> bool:
        import pygetwindow

        matches = pygetwindow.getWindowsWithTitle(target)
        if not matches:
            return False
        matches[0].close()
        return True

    def shutdown(self) -> None:
        subprocess.run(["shutdown", "/s", "/t", "0"], check=True)

    def restart(self) -> None:
        subprocess.run(["shutdown", "/r", "/t", "0"], check=True)

    def click(self, x: int, y: int, button: str = "left") -> None:
        screen.click(x, y, button)

    def move_mouse(self, x: int, y: int) -> None:
        screen.move_mouse(x, y)

    def type_text(self, text: str) -> None:
        screen.type_text(text)

    def press_key(self, key: str) -> None:
        screen.press_key(key)

    def list_windows(self) -> list[str]:
        import pygetwindow

        return [title for title in pygetwindow.getAllTitles() if title]

    def focus_window(self, title: str) -> bool:
        import pygetwindow

        matches = pygetwindow.getWindowsWithTitle(title)
        if not matches:
            return False
        window = matches[0]
        if window.isMinimized:
            window.restore()
        window.activate()
        return True

    def get_active_window(self) -> ActiveWindow | None:
        import pygetwindow

        window = pygetwindow.getActiveWindow()
        if window is None:
            return None
        # pygetwindow doesn't expose a PID; not needed on this platform
        # anyway, since the AT-SPI-based grounding that consumes it
        # (modules/ui_automation) is Linux-only this round — this method
        # only exists for OSAdapter's per-OS symmetry. bbox is cheap to
        # include (pygetwindow already tracks it) for modules/ui_automation's
        # OCR fallback (see ocr_adapter.py), which works cross-platform.
        return ActiveWindow(
            title=window.title,
            pid=None,
            bbox=(window.left, window.top, window.width, window.height),
        )
