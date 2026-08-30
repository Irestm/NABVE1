from __future__ import annotations

import threading

from modules.gesture_control.config import CURSOR_SCALE

# The enlarged cursor itself is drawn by a transparent, click-through
# Electron BrowserWindow (frontend/electron/gestureOverlay.ts) that follows
# the real OS cursor. The backend only publishes "is gesture mode on" (and
# the fixed magnification, so the overlay window sizes itself) — the
# frontend reads this off /api/status and toggles the overlay window.


class _OverlayState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = False

    def set(self, *, active: bool) -> None:
        with self._lock:
            self._active = active

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    @property
    def scale(self) -> float:
        return CURSOR_SCALE


overlay_state = _OverlayState()
