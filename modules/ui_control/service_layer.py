from __future__ import annotations

from core.state import StateManager


def show_window(state: StateManager) -> None:
    state.request_ui_visibility("show")


def hide_window(state: StateManager) -> None:
    state.request_ui_visibility("hide")
