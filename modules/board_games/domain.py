from __future__ import annotations

import enum
from dataclasses import dataclass


class GameKind(str, enum.Enum):
    CHESS = "chess"
    CHECKERS = "checkers"


class Difficulty(str, enum.Enum):
    """Plain-words difficulty tiers — see chess_adapter._DIFFICULTY_ELO and
    checkers_adapter._DIFFICULTY_DEPTH for what each maps to per game.
    Optional everywhere it's accepted: omitting it (None) preserves each
    adapter's original, pre-difficulty-selector default engine strength
    (full-strength Stockfish for chess, depth 6 for checkers) — matters
    because core/voice/pipeline.py's voice-driven games start one without
    ever passing a difficulty."""

    VERY_EASY = "very_easy"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    VERY_HARD = "very_hard"
    IMPOSSIBLE = "impossible"


@dataclass(frozen=True)
class MoveJudgement:
    """The engine's verdict on one player move, computed by
    modules.board_games.chess_adapter/checkers_adapter's apply_player_move
    while the position was still fresh. `was_mistake` gates whether
    `better_move`/`eval_delta` are worth surfacing at all — see
    modules.board_games.service_layer.resolve_player_move, the only
    producer of these."""

    notation: str
    was_mistake: bool
    better_move: str | None = None
    eval_delta: float | None = None


@dataclass(frozen=True)
class EngineMove:
    """The engine's own move, with its from/to squares alongside the
    notation string — unlike a player's move (whose origin square the UI
    already knows, from whichever square they clicked), the frontend has
    no other way to find where the engine's piece started, so
    chess_adapter/checkers_adapter.apply_engine_move captures this while
    the move object is still in hand, before collapsing it to a string.
    Used to drive BoardGamesPanel.tsx's slide animation for the engine's
    reply."""

    notation: str
    from_square: str
    to_square: str


@dataclass(frozen=True)
class GameSummary:
    """Built once, at game end, by modules.board_games.service_layer.finish
    — raw data, not spoken text: modules.board_games.announce is what
    turns `result_string` (a PGN-style "1-0"/"0-1"/"1/2-1/2" — see
    chess_adapter/checkers_adapter's own result_string docstrings) and
    `mistakes` (only ever entries where was_mistake is True) into what
    core/voice/pipeline.py actually speaks — same division of labour as
    modules.ui_automation.grounding (structured data) vs.
    modules.ui_automation.announce (text)."""

    result_string: str
    mistakes: tuple[MoveJudgement, ...]
    board_svg: str
