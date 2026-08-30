from __future__ import annotations

import threading

from modules.gesture_control.config import DEFAULT_CURSOR_SCALE

# The enlarged cursor itself is drawn by a transparent, click-through
# Electron BrowserWindow (frontend/electron/gestureOverlay.ts) that follows
# the real OS cursor via screen.getCursorScreenPoint(). The backend only
# needs to publish "is gesture mode on, and at what cursor scale" — the
# frontend reads this off /api/status and toggles/sizes the overlay window.


class _OverlayState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = False
        self._scale = DEFAULT_CURSOR_SCALE

    def set(self, *, active: bool | None = None, scale: float | None = None) -> None:
        with self._lock:
            if active is not None:
                self._active = active
            if scale is not None:
                self._scale = scale

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    @property
    def scale(self) -> float:
        with self._lock:
            return self._scale


overlay_state = _OverlayState()
