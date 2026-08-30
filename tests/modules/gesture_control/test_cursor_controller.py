from __future__ import annotations

from modules.gesture_control.cursor_controller import bounds_from_zone, map_hand_to_screen

SCREEN = (1920, 1080)


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
