from __future__ import annotations

import threading

from core.models import AssistantState


class StateManager:
    def __init__(self) -> None:
        self._state: AssistantState = AssistantState.IDLE
        self._detail: str = ""
        self._lock = threading.Lock()
        # Set by the "show_window"/"hide_window" commands (reachable via voice or
        # the API) and polled+cleared by Electron's main process, since the Python
        # backend has no direct handle to the renderer's BrowserWindow.
        self._ui_visibility_request: str | None = None
        # Same mailbox shape as _ui_visibility_request above, for a
        # different consumer: set by core/voice/pipeline.py::_resolve_board_game
        # at the end of a chess/draughts game (an SVG string, not base64 —
        # see request_image's own docstring for why), polled+cleared by the
        # frontend directly (not Electron's main process — nothing here
        # needs OS window control, just rendering, which belongs to the
        # renderer) via GET /api/ui/image_request.
        self._image_request: str | None = None

    @property
    def state(self) -> AssistantState:
        with self._lock:
            return self._state

    @property
    def detail(self) -> str:
        with self._lock:
            return self._detail

    def set_state(self, state: AssistantState, detail: str = "") -> None:
        with self._lock:
            self._state = state
            self._detail = detail

    def request_ui_visibility(self, action: str) -> None:
        with self._lock:
            self._ui_visibility_request = action

    def consume_ui_visibility_request(self) -> str | None:
        with self._lock:
            action = self._ui_visibility_request
            self._ui_visibility_request = None
            return action

    def request_image(self, svg: str) -> None:
        """`svg` is a plain SVG string (what chess.svg.board()/
        draughts.svg.board() already return) — no base64 needed, JSON can
        carry text directly; the frontend is the one that turns it into a
        data: URI for an <img> tag."""
        with self._lock:
            self._image_request = svg

    def consume_image_request(self) -> str | None:
        with self._lock:
            svg = self._image_request
            self._image_request = None
            return svg


state_manager = StateManager()
