from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core.config import LOGS_DIR

# Separate from core.logger's per-module RotatingFileHandler (5 backups,
# rotated/deleted on size) — a record of every privileged filesystem/system
# operation (delete_folder with force_admin, change_system_locale) must
# survive regardless of how noisy the regular app log gets, per this
# project's explicit requirement that these operations stay auditable.
# One shared file for both platform adapters since it's cross-platform
# machinery, not something either windows.py/linux.py owns individually.
_AUDIT_LOG_PATH = LOGS_DIR / "audit_privileged_ops.log"



def log_privileged_action(
    action: str,
    *,
    path: str | None = None,
    elevation: str | None = None,
    success: bool,
    detail: str = "",
) -> None:
    """Appends one JSON line per privileged operation (destructive delete,
    admin-elevated delete, system locale change, ...). Append-only, never
    truncated or rotated — this is a durable audit trail, not a debug log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "path": path,
        "elevation_mechanism": elevation,
        "success": success,
        "detail": detail,
    }
    with _AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


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

    # --- volume ---

    @abstractmethod
    def set_volume(self, percent: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def change_volume(self, delta_percent: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_volume(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def mute(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def unmute(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def toggle_mute(self) -> bool:
        """Returns the new muted state (True = now muted)."""
        raise NotImplementedError

    # --- brightness ---

    @abstractmethod
    def set_brightness(self, percent: int) -> None:
        """Sets the primary display's brightness to an exact level. Callers
        pass 0-100; implementations clamp to a safe floor above 0 so a voice
        command can never leave the user with an unrecoverable black screen."""
        raise NotImplementedError

    @abstractmethod
    def change_brightness(self, delta_percent: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_brightness(self) -> int:
        raise NotImplementedError

    # --- session ---

    @abstractmethod
    def lock_screen(self) -> None:
        """Locks the desktop session (requires the user's password to return),
        distinct from shutdown()/restart() — nothing is closed and no running
        work is lost. Raises RuntimeError when no supported locking mechanism
        is available on this platform/desktop environment."""
        raise NotImplementedError

    # --- windows / tabs ---

    @abstractmethod
    def hide_window(self, app_name: str | None) -> bool:
        """Minimizes the window of `app_name` (partial title match), or the
        currently active window when app_name is None."""
        raise NotImplementedError

    @abstractmethod
    def close_window(self, app_name: str | None) -> bool:
        """Gracefully closes the window of `app_name` (partial title match),
        or the currently active window when app_name is None. Never kills
        the process directly."""
        raise NotImplementedError

    @abstractmethod
    def close_tab(self) -> None:
        """Sends Ctrl+W to whatever currently has focus — there is no OS-level
        API for an individual browser tab without a browser extension."""
        raise NotImplementedError

    # --- filesystem ---

    @abstractmethod
    def create_folder(self, path: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def move_folder(self, source: str, destination: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def delete_folder(self, path: str, force_admin: bool = False) -> dict[str, Any]:
        """Never called directly on unconfirmed user intent — see
        core/dispatcher.py's dangerous=True registration for this command,
        which forces an explicit voice confirmation before this method ever
        runs. Logs to the audit trail (see log_privileged_action above)
        whenever force_admin is used."""
        raise NotImplementedError

    # --- system language ---

    @abstractmethod
    def switch_keyboard_layout(self, language_code: str) -> dict[str, Any]:
        """Cheap, immediate: just the active keyboard input layout, not the
        whole system locale (see change_system_locale for that)."""
        raise NotImplementedError

    @abstractmethod
    def change_system_locale(self, language_code: str) -> dict[str, Any]:
        """Heavier than switch_keyboard_layout: changes the system-wide
        locale, typically requires elevated privileges and may require a
        logout/restart to fully apply — the returned dict's "message" key
        says so when relevant."""
        raise NotImplementedError

    # --- device / system status ---

    @abstractmethod
    def get_battery_status(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def check_system_updates(self) -> dict[str, Any]:
        """Checks only — never installs anything."""
        raise NotImplementedError
