from __future__ import annotations

from core.logger import get_logger
from modules.board_games import service_layer
from modules.board_games.domain import Difficulty, GameKind, GameSummary

logger = get_logger(__name__)

# The single source of truth for "the current board game" — read and
# written by both core/main.py's /api/boardgames/* REST endpoints (and
# therefore BoardGamesPanel.tsx) AND core/voice/pipeline.py's
# _resolve_board_game/_resolve_active_board_game_utterance/
# _resolve_board_game_move. A game started by clicking "Начать шахматы" can
# be played by voice, and vice versa — same GameSession either way. One
# game at a time, simplest correct model for a single-user local app, same
# as modules.quizlet_clone.quizlet_auth's one module-level session.
_current: service_layer.GameSession | None = None


def start(kind: GameKind, difficulty: Difficulty | None = None) -> service_layer.GameSession:
    global _current
    if _current is not None:
        # Release the previous game's resources (Stockfish subprocess, for
        # chess) before starting a new one — nothing else does this if the
        # user abandons a game mid-way by just starting another.
        service_layer.finish(_current)
    _current = service_layer.start_game(kind, difficulty)
    return _current


def current() -> service_layer.GameSession | None:
    return _current


def require_current() -> service_layer.GameSession:
    if _current is None:
        raise RuntimeError("Игра ещё не начата — сначала нажмите «Шахматы» или «Шашки».")
    return _current


def finish() -> GameSummary | None:
    global _current
    if _current is None:
        return None
    summary = service_layer.finish(_current)
    _current = None
    return summary
