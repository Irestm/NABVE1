from __future__ import annotations

from types import ModuleType

from core.logger import get_logger

logger = get_logger(__name__)

_ZOOM_SCROLL_CLICKS = 2


def _require_pyautogui() -> ModuleType:
    import pyautogui

    # In the gesture worker we drive the cursor many times a second from
    # hand tracking — pyautogui's global 0.1s post-call PAUSE would make it
    # unusable, and FAILSAFE (abort when the pointer hits a screen corner)
    # would fire constantly on fast hand moves. Both are scoped to this
    # process, which only exists while gesture mode is on.
    pyautogui.PAUSE = 0
    pyautogui.FAILSAFE = False
    return pyautogui


def map_hand_to_screen(
    hand_xy: tuple[float, float],
    screen_size: tuple[int, int],
    zone_fraction: float,
) -> tuple[int, int]:
    """Maps a normalized hand point (0..1 within the camera frame) to an
    absolute screen pixel. Only the central `zone_fraction` of the frame is
    the active area — mapping the whole frame to the whole screen makes
    control far too coarse (a tiny hand move flings the cursor across the
    display). Points outside the zone clamp to the screen edge."""
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
    a held click (so a pinch-and-drag works), and a zoom nudge. Cross-
    platform; on Linux this needs an X11 session (pyautogui uses Xlib) —
    same limitation as the wmctrl/xdotool tools elsewhere."""

    def __init__(self) -> None:
        self._pyautogui = _require_pyautogui()
        self._button_down = False
        self.screen_size: tuple[int, int] = tuple(self._pyautogui.size())  # (w, h)

    def move_cursor(self, x: int, y: int) -> None:
        self._pyautogui.moveTo(x, y, _pause=False)

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
        # Ctrl+wheel is the near-universal "zoom" in browsers, editors,
        # image viewers, map apps, ...
        self._pyautogui.keyDown("ctrl")
        try:
            self._pyautogui.scroll(amount)
        finally:
            self._pyautogui.keyUp("ctrl")

    def release(self) -> None:
        """Best-effort: make sure we never leave a mouse button stuck down
        when gesture mode is turned off mid-pinch."""
        try:
            self.click_up()
        except Exception:
            logger.debug("click_up during release raised", exc_info=True)
