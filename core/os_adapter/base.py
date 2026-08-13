from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ActiveWindow:
    title: str
    pid: int | None
    # X11 WM_CLASS (Linux only — always None on Windows). Used to route
    # UI-action element lookup: modules.ui_automation.service_layer picks a
    # browser-specific (CDP) element inspector for known Chromium wm_class
    # values, AT-SPI for everything else.
    wm_class: str | None = None
    # x, y, width, height in absolute screen pixels — the same coordinate
    # space core/os_adapter's click()/move_mouse() already operate in (see
    # modules/ui_automation/domain.py's UIElement.bbox comment). None when
    # window geometry couldn't be determined; callers that need it
    # (currently only modules/ui_automation/ocr_adapter.py's screenshot
    # capture) fall back to the whole primary screen instead.
    bbox: tuple[int, int, int, int] | None = None


class OSAdapter(ABC):
    @abstractmethod
    def open_application(self, target: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def close_application(self, target: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def shutdown(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def restart(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def click(self, x: int, y: int, button: str = "left") -> None:
        raise NotImplementedError

    @abstractmethod
    def move_mouse(self, x: int, y: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def type_text(self, text: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def press_key(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_windows(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def focus_window(self, title: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get_active_window(self) -> ActiveWindow | None:
        raise NotImplementedError
