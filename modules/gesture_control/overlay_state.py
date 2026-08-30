from __future__ import annotations

import threading

from modules.gesture_control.calibration import CalibrationProgress

# Process-wide gesture-mode state read by core/main.py for /api/status: the
# on/off flag plus, while the calibration wizard runs, its current step so
# the frontend can draw the "5 dots" progress. The enlarged cursor itself is
# the OS's own pointer (cursor_zoom.py) — there is no overlay window.


class _OverlayState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = False
        self._calibration: CalibrationProgress | None = None

    def set(self, *, active: bool) -> None:
        with self._lock:
            self._active = active
            if not active:
                self._calibration = None

    def set_calibration(self, progress: CalibrationProgress | None) -> None:
        with self._lock:
            self._calibration = progress

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    @property
    def calibration(self) -> CalibrationProgress | None:
        with self._lock:
            return self._calibration


overlay_state = _OverlayState()
