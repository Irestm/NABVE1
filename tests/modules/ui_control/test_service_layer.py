from __future__ import annotations

from core.state import StateManager
from modules.ui_control import service_layer


def test_show_window_sets_a_consumable_show_request() -> None:
    state = StateManager()

    service_layer.show_window(state)

    assert state.consume_ui_visibility_request() == "show"
    assert state.consume_ui_visibility_request() is None


def test_hide_window_sets_a_consumable_hide_request() -> None:
    state = StateManager()

    service_layer.hide_window(state)

    assert state.consume_ui_visibility_request() == "hide"
