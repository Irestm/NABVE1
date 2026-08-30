from __future__ import annotations

import math
from types import ModuleType

from core.logger import get_logger

logger = get_logger(__name__)

_ZOOM_SCROLL_CLICKS = 2


def _require_pyautogui() -> ModuleType:
    import pyautogui

    # Driven many times a second from hand tracking — pyautogui's global
    # 0.1s post-call PAUSE would make it unusable, and FAILSAFE (abort on a
    # screen-corner hit) would fire on fast hand moves. Both scoped to this
    # process, which only lives while gesture mode is on.
    pyautogui.PAUSE = 0
    pyautogui.FAILSAFE = False
    return pyautogui


def _virtual_screen_size(pyautogui: ModuleType) -> tuple[int, int]:
    """The full virtual desktop, spanning every monitor. pyautogui.size()
    returns only the primary screen on a multi-monitor X11 setup, which
    would trap the gesture cursor on one monitor and land clicks off-target.
    Xlib (already a pyautogui dependency on Linux) gives the real span."""
    try:
        from Xlib.display import Display  # type: ignore[import-untyped]

        geom = Display().screen().root.get_geometry()
        if geom.width > 0 and geom.height > 0:
            return int(geom.width), int(geom.height)
    except Exception:
        logger.debug("Xlib virtual screen size lookup failed, using pyautogui.size()", exc_info=True)
    size = pyautogui.size()
    return int(size[0]), int(size[1])


def bounds_from_zone(zone_fraction: float) -> tuple[float, float, float, float]:
    """The symmetric central-square tracking rectangle for a zone fraction —
    the fallback when the corner-tracing calibration phase hasn't run."""
    zone = max(0.2, min(1.0, zone_fraction))
    margin = (1.0 - zone) / 2
    return (margin, 1.0 - margin, margin, 1.0 - margin)


def map_hand_to_screen(
    hand_xy: tuple[float, float],
    screen_size: tuple[int, int],
    bounds: tuple[float, float, float, float],
) -> tuple[int, int]:
    """Maps a normalized hand point (0..1 within the mirrored camera frame)
    to an absolute screen pixel. `bounds` is (x0, x1, y0, y1) — the frame
    rectangle that maps to the whole screen (personalised by the corner
    calibration, or a central square via bounds_from_zone). Points outside
    it clamp to the screen edge."""
    x0, x1, y0, y1 = bounds

    def _axis(value: float, lo: float, hi: float, extent: int) -> int:
        span = hi - lo if hi - lo > 1e-4 else 1e-4
        clamped = max(0.0, min(1.0, (value - lo) / span))
        return int(round(clamped * (extent - 1)))

    width, height = screen_size
    return _axis(hand_xy[0], x0, x1, width), _axis(hand_xy[1], y0, y1, height)


class CursorController:
    """Thin wrapper over pyautogui for the gesture worker: absolute moves,
    a held click (pinch-and-drag), a zoom nudge, and a check for whether the
    *physical* mouse has been touched since our last move. Cross-platform;
    on Linux needs an X11 session (pyautogui uses Xlib)."""

    def __init__(self) -> None:
        self._pyautogui = _require_pyautogui()
        self._button_down = False
        self._last_set: tuple[int, int] | None = None
        self.screen_size: tuple[int, int] = _virtual_screen_size(self._pyautogui)  # (w, h)

    def current_pos(self) -> tuple[int, int]:
        point = self._pyautogui.position()
        return int(point[0]), int(point[1])

    def physical_mouse_moved(self, threshold_px: int) -> bool:
        """True if the OS cursor is now more than `threshold_px` away from
        where this controller last put it — i.e. something else (the real
        mouse / touchpad) moved it."""
        if self._last_set is None:
            return False
        cx, cy = self.current_pos()
        return math.hypot(cx - self._last_set[0], cy - self._last_set[1]) > threshold_px

    def move_cursor(self, x: int, y: int) -> None:
        self._pyautogui.moveTo(x, y, _pause=False)
        self._last_set = (x, y)

    def sync_last_set(self) -> None:
        """Re-anchor _last_set to the real cursor position — call after
        yielding to the physical mouse so we don't immediately re-trigger
        the physical-move check on the frame we resume."""
        self._last_set = self.current_pos()

    def click_down(self) -> None:
        if not self._button_down:
            self._pyautogui.mouseDown(_pause=False)
            self._button_down = True

    def click_up(self) -> None:
        if self._button_down:
            self._pyautogui.mouseUp(_pause=False)
            self._button_down = False

    @property
    def is_holding(self) -> bool:
        return self._button_down

    def trigger_zoom(self, direction: str) -> None:
        amount = _ZOOM_SCROLL_CLICKS if direction == "in" else -_ZOOM_SCROLL_CLICKS
        self._pyautogui.keyDown("ctrl")
        try:
            self._pyautogui.scroll(amount)
        finally:
            self._pyautogui.keyUp("ctrl")

    def trigger_window_switch(self, direction: str) -> None:
        if direction == "prev":
            self._pyautogui.hotkey("alt", "shift", "tab")
        else:
            self._pyautogui.hotkey("alt", "tab")

    def release(self) -> None:
        try:
            self.click_up()
        except Exception:
            logger.debug("click_up during release raised", exc_info=True)
