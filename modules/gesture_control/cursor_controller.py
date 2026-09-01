from __future__ import annotations

import math
import os
import sys
from types import ModuleType

from core.logger import get_logger

logger = get_logger(__name__)



def _no_display_hint(exc: object) -> str:
    """A pyautogui/Xlib import or call failed. On Linux that is almost always
    a Wayland session (pyautogui drives the cursor through X11) — say so."""
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if sys.platform.startswith("linux") and (session == "wayland" or not os.environ.get("DISPLAY")):
        return (
            "Режим жестов управляет системным курсором через X11, а текущий сеанс — "
            f"Wayland или без DISPLAY ({exc}). На экране входа выберите «Ubuntu on Xorg» "
            "и повторите."
        )
    return f"Не удалось инициализировать управление курсором: {exc}"


def _require_pyautogui() -> tuple[ModuleType, float, bool]:
    try:
        import pyautogui
    except Exception as exc:  # Xlib raises its own errors, not just ImportError
        raise RuntimeError(_no_display_hint(exc)) from exc

    # Driven many times a second from hand tracking — pyautogui's global
    # 0.1s post-call PAUSE would make it unusable, and FAILSAFE (abort on a
    # screen-corner hit) would fire on fast hand moves. These are MODULE
    # globals shared with every other pyautogui user in this process
    # (os_adapter/screen, figma_control, software_installer, ui_automation),
    # so the originals are returned and put back in CursorController.release().
    prev_pause, prev_failsafe = pyautogui.PAUSE, pyautogui.FAILSAFE
    pyautogui.PAUSE = 0
    pyautogui.FAILSAFE = False
    return pyautogui, prev_pause, prev_failsafe


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
    try:
        size = pyautogui.size()
        return int(size[0]), int(size[1])
    except Exception:
        logger.debug("pyautogui.size() failed too", exc_info=True)
        return 0, 0


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
        self._pyautogui, self._prev_pause, self._prev_failsafe = _require_pyautogui()
        self._button_down = False
        self._last_set: tuple[int, int] | None = None
        # The target we last *commanded*. pyautogui.moveTo can return before
        # the OS pointer has settled, so an immediate position() read after a
        # move lags behind — checking against the commanded target too stops
        # that lag from reading as a physical-mouse move on the next tick.
        self._last_cmd: tuple[int, int] | None = None
        self.screen_size: tuple[int, int] = _virtual_screen_size(self._pyautogui)  # (w, h)
        if self.screen_size[0] <= 0 or self.screen_size[1] <= 0:
            self._restore_pyautogui_globals()
            raise RuntimeError(_no_display_hint("не удалось определить размер экрана"))

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
        far_from_set = math.hypot(cx - self._last_set[0], cy - self._last_set[1]) > threshold_px
        if not far_from_set:
            return False
        if self._last_cmd is not None:
            # Close to where we last told it to go -> it's our own move
            # catching up, not the physical mouse.
            if math.hypot(cx - self._last_cmd[0], cy - self._last_cmd[1]) <= threshold_px:
                return False
        return True

    def move_cursor(self, x: int, y: int) -> None:
        self._pyautogui.moveTo(x, y, _pause=False)
        self._last_cmd = (x, y)
        # Record where the cursor ACTUALLY landed, not what we asked for: the
        # OS clamps the pointer out of reserved areas (a dock / panel), and
        # anchoring _last_set to the unreachable target made every following
        # tick read as a physical-mouse move and freeze gesture control near
        # that edge.
        try:
            self._last_set = self.current_pos()
        except Exception:
            self._last_set = (x, y)

    def last_pos(self) -> tuple[int, int] | None:
        """Where the cursor actually ended up after the last move (or None
        if we've never moved it) — the caller uses this to keep its float
        accumulator from winding up past the reachable area."""
        return self._last_set

    def sync_last_set(self) -> None:
        """Re-anchor both references to the real cursor position — call after
        yielding to the physical mouse (or any frame we don't move) so we
        don't immediately re-trigger the physical-move check next tick."""
        pos = self.current_pos()
        self._last_set = pos
        self._last_cmd = pos

    def click_down(self) -> None:
        if not self._button_down:
            self._pyautogui.mouseDown(_pause=False)
            self._button_down = True

    def click_up(self) -> None:
        if self._button_down:
            self._pyautogui.mouseUp(_pause=False)
            self._button_down = False

    def right_click(self) -> None:
        """A one-shot right click (never held). Released left button first so
        we never right-click mid-drag."""
        self.click_up()
        self._pyautogui.click(button="right", _pause=False)

    def scroll(self, clicks: int) -> None:
        """Turn the mouse wheel `clicks` notches (positive = up)."""
        if clicks:
            self._pyautogui.scroll(int(clicks), _pause=False)

    @property
    def is_holding(self) -> bool:
        return self._button_down

    def _restore_pyautogui_globals(self) -> None:
        try:
            self._pyautogui.PAUSE = self._prev_pause
            self._pyautogui.FAILSAFE = self._prev_failsafe
        except Exception:
            logger.debug("restoring pyautogui globals raised", exc_info=True)

    def release(self) -> None:
        try:
            self.click_up()
        except Exception:
            logger.debug("click_up during release raised", exc_info=True)
        # Hand PAUSE / FAILSAFE back to whatever the rest of the process had,
        # so other pyautogui users keep their corner-abort safety.
        self._restore_pyautogui_globals()
