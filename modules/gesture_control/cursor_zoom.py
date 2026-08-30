from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading

from core.logger import get_logger
from modules.gesture_control.config import CURSOR_SCALE

logger = get_logger(__name__)

# The enlarged cursor while gesture mode is on is the OS's *own* pointer,
# resized in place — not a separate overlay window that trails behind it
# (the user saw that as a doubled cursor). On GNOME/X11 the live pointer
# size is org.gnome.desktop.interface cursor-size, same gsettings surface
# core/os_adapter/linux.py already uses for the keyboard layout fallback.
# Elsewhere (other Linux DEs, Windows) there is no dependency-free live
# resize, so enlarge()/restore() are a logged no-op.

_GSETTINGS_SCHEMA = "org.gnome.desktop.interface"
_GSETTINGS_KEY = "cursor-size"
_MAX_CURSOR_SIZE = 128
# `gsettings get` prints e.g. "uint32 24" — take the trailing integer, not
# the "32" inside the type tag.
_INT_RE = re.compile(r"(\d+)\s*$")


class CursorZoom:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._original: int | None = None

    def enlarge(self) -> None:
        with self._lock:
            if self._original is not None:
                return
            current = self._read_gnome_cursor_size()
            if current is None:
                return
            target = min(_MAX_CURSOR_SIZE, max(current + 1, round(current * CURSOR_SCALE)))
            if self._write_gnome_cursor_size(target):
                self._original = current
                logger.info("Gesture mode: cursor size %d -> %d", current, target)

    def restore(self) -> None:
        with self._lock:
            if self._original is None:
                return
            self._write_gnome_cursor_size(self._original)
            logger.info("Gesture mode: cursor size restored to %d", self._original)
            self._original = None

    def _gsettings(self) -> str | None:
        if not sys.platform.startswith("linux"):
            return None
        return shutil.which("gsettings")

    def _read_gnome_cursor_size(self) -> int | None:
        tool = self._gsettings()
        if tool is None:
            return None
        try:
            result = subprocess.run(
                [tool, "get", _GSETTINGS_SCHEMA, _GSETTINGS_KEY],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
        except (subprocess.SubprocessError, OSError):
            logger.debug("gsettings get cursor-size failed", exc_info=True)
            return None
        match = _INT_RE.search(result.stdout.strip())
        return int(match.group(1)) if match else None

    def _write_gnome_cursor_size(self, size: int) -> bool:
        tool = self._gsettings()
        if tool is None:
            return False
        try:
            subprocess.run(
                [tool, "set", _GSETTINGS_SCHEMA, _GSETTINGS_KEY, str(size)],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
        except (subprocess.SubprocessError, OSError):
            logger.debug("gsettings set cursor-size failed", exc_info=True)
            return False
        return True


cursor_zoom = CursorZoom()
