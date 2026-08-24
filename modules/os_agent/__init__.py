from __future__ import annotations

# No register_commands here — unlike most modules, os_agent has no
# CommandDispatcher-registered command of its own (mirrors
# modules.board_games's start_board_game: a pure voice-loop state machine,
# not a REST-reachable command; no frontend panel needs one either). Its
# only externally-dispatched effect reuses the already-registered
# modules.ui_automation "ui_action" command — see
# core/voice/pipeline.py::_dispatch_ui_steps.
