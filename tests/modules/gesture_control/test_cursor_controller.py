from __future__ import annotations

from modules.gesture_control.cursor_controller import (
    _no_display_hint,
    bounds_from_zone,
    map_hand_to_screen,
)

SCREEN = (1920, 1080)


def test_no_display_hint_calls_out_wayland(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.delenv("DISPLAY", raising=False)
    msg = _no_display_hint("boom")
    assert "Wayland" in msg and "Xorg" in msg


def test_no_display_hint_is_generic_off_wayland(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("DISPLAY", ":0")
    assert "Wayland" not in _no_display_hint("boom")


def test_release_restores_pyautogui_globals(monkeypatch) -> None:
    import sys
    import types

    fake = types.SimpleNamespace(
        PAUSE=0.1,
        FAILSAFE=True,
        position=lambda: (5, 5),
        size=lambda: (100, 80),
        moveTo=lambda *a, **k: None,
        mouseDown=lambda **k: None,
        mouseUp=lambda **k: None,
    )
    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    from modules.gesture_control.cursor_controller import CursorController

    c = CursorController()
    assert fake.PAUSE == 0 and fake.FAILSAFE is False  # gesture mode disabled them
    c.release()
    assert fake.PAUSE == 0.1 and fake.FAILSAFE is True  # handed back to the process


def test_physical_move_check_tolerates_lagging_position_reads(monkeypatch) -> None:
    import sys
    import types

    pos = {"xy": (0, 0)}
    fake = types.SimpleNamespace(
        PAUSE=0,
        FAILSAFE=False,
        position=lambda: pos["xy"],
        size=lambda: (1920, 1080),
        moveTo=lambda *a, **k: None,  # NB: does NOT update pos -> simulates lag
        mouseDown=lambda **k: None,
        mouseUp=lambda **k: None,
    )
    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    from modules.gesture_control.cursor_controller import CursorController

    c = CursorController()
    c.move_cursor(900, 500)                 # commanded far; position() still (0,0)
    pos["xy"] = (900, 500)                  # OS pointer catches up next tick
    assert c.physical_mouse_moved(18) is False  # our own move landing, not the mouse
    pos["xy"] = (200, 700)                  # now something else yanked it away
    assert c.physical_mouse_moved(18) is True


def test_bounds_from_zone_is_a_centred_square() -> None:
    assert bounds_from_zone(0.6) == (0.2, 0.8, 0.2, 0.8)
    assert bounds_from_zone(1.0) == (0.0, 1.0, 0.0, 1.0)


def test_centre_of_bounds_maps_to_centre_of_screen() -> None:
    x, y = map_hand_to_screen((0.5, 0.5), SCREEN, (0.2, 0.8, 0.2, 0.8))
    assert abs(x - 960) <= 1
    assert abs(y - 540) <= 1


def test_bounds_edges_map_to_screen_edges() -> None:
    left, top = map_hand_to_screen((0.2, 0.2), SCREEN, (0.2, 0.8, 0.2, 0.8))
    right, bottom = map_hand_to_screen((0.8, 0.8), SCREEN, (0.2, 0.8, 0.2, 0.8))
    assert (left, top) == (0, 0)
    assert (right, bottom) == (1919, 1079)


def test_points_outside_bounds_clamp_to_the_edge() -> None:
    assert map_hand_to_screen((0.05, 0.5), SCREEN, (0.2, 0.8, 0.2, 0.8))[0] == 0
    assert map_hand_to_screen((0.95, 0.5), SCREEN, (0.2, 0.8, 0.2, 0.8))[0] == 1919


def test_asymmetric_bounds_from_corner_calibration() -> None:
    # A rectangle that isn't centred — the corner phase can produce this.
    bounds = (0.15, 0.9, 0.3, 0.75)
    x0, _ = map_hand_to_screen((0.15, 0.3), SCREEN, bounds)
    x1, _ = map_hand_to_screen((0.9, 0.3), SCREEN, bounds)
    _, ytop = map_hand_to_screen((0.5, 0.3), SCREEN, bounds)
    _, ybot = map_hand_to_screen((0.5, 0.75), SCREEN, bounds)
    assert x0 == 0 and x1 == 1919
    assert ytop == 0 and ybot == 1079


def test_degenerate_bounds_do_not_divide_by_zero() -> None:
    x, _ = map_hand_to_screen((0.5, 0.5), SCREEN, (0.5, 0.5, 0.5, 0.5))
    assert 0 <= x <= 1919
