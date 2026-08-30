from __future__ import annotations

import threading

# Process-wide "is gesture mode on" flag. core/main.py exposes it on
# /api/status so the frontend can show a small indicator; the enlarged
# cursor itself is the OS's own pointer, resized by cursor_zoom.py — there
# is no overlay window any more.


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


overlay_state = _OverlayState()
