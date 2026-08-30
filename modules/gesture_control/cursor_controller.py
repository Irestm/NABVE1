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


def map_hand_to_screen(
    hand_xy: tuple[float, float],
    screen_size: tuple[int, int],
    zone_fraction: float,
) -> tuple[int, int]:
    """Maps a normalized hand point (0..1 within the mirrored camera frame)
    to an absolute screen pixel. Only the central `zone_fraction` of the
    frame is active — mapping the whole frame to the whole screen makes
    control far too coarse. Points outside the zone clamp to the edge."""
    zone = max(0.2, min(1.0, zone_fraction))
    margin = (1.0 - zone) / 2

    def _axis(value: float, extent: int) -> int:
        normalized = (value - margin) / zone
        clamped = max(0.0, min(1.0, normalized))
        return int(round(clamped * (extent - 1)))

    width, height = screen_size
    return _axis(hand_xy[0], width), _axis(hand_xy[1], height)


class CursorController:
    """Thin wrapper over pyautogui for the gesture worker: absolute moves,
    a held click (pinch-and-drag), a zoom nudge, and a check for whether the
    *physical* mouse has been touched since our last move. Cross-platform;
    on Linux needs an X11 session (pyautogui uses Xlib)."""

    def __init__(self) -> None:
        self._pyautogui = _require_pyautogui()
        self._button_down = False
        self._last_set: tuple[int, int] | None = None
        self.screen_size: tuple[int, int] = tuple(self._pyautogui.size())  # (w, h)

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

    def release(self) -> None:
        try:
            self.click_up()
        except Exception:
            logger.debug("click_up during release raised", exc_info=True)
