from __future__ import annotations

from modules.gesture_control.cursor_controller import map_hand_to_screen


SCREEN = (1920, 1080)


def test_centre_of_zone_maps_to_centre_of_screen() -> None:
    x, y = map_hand_to_screen((0.5, 0.5), SCREEN, zone_fraction=0.6)
    assert abs(x - 960) <= 1
    assert abs(y - 540) <= 1


def test_zone_edges_map_to_screen_edges() -> None:
    # zone 0.6 -> active band is 0.2..0.8 of the frame.
    left, top = map_hand_to_screen((0.2, 0.2), SCREEN, zone_fraction=0.6)
    right, bottom = map_hand_to_screen((0.8, 0.8), SCREEN, zone_fraction=0.6)
    assert (left, top) == (0, 0)
    assert (right, bottom) == (1919, 1079)


def test_points_outside_the_zone_clamp_to_the_edge() -> None:
    assert map_hand_to_screen((0.05, 0.5), SCREEN, zone_fraction=0.6)[0] == 0
    assert map_hand_to_screen((0.95, 0.5), SCREEN, zone_fraction=0.6)[0] == 1919


def test_smaller_zone_makes_control_finer() -> None:
    # A 0.1 hand move near centre travels further on screen with a tighter zone.
    wide = map_hand_to_screen((0.6, 0.5), SCREEN, zone_fraction=0.9)[0]
    tight = map_hand_to_screen((0.6, 0.5), SCREEN, zone_fraction=0.4)[0]
    assert tight > wide


def test_zone_fraction_is_clamped_to_a_sane_minimum() -> None:
    # zone 0.0 would divide by zero — the impl floors it.
    x, _ = map_hand_to_screen((0.5, 0.5), SCREEN, zone_fraction=0.0)
    assert 0 <= x <= 1919
