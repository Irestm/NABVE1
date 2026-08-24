from __future__ import annotations

import re
from dataclasses import dataclass

import draughts
import draughts.svg

from core.logger import get_logger
from modules.board_games.domain import Difficulty, EngineMove, MoveJudgement

logger = get_logger(__name__)

_ENGINE_DEPTH = 6
# SimpleEngine's own evaluation scale (roughly "material advantage in
# pieces"), not centipawns — not directly comparable to chess_adapter's
# threshold, this one was picked empirically against the same engine.
_MISTAKE_THRESHOLD = 1.0

# Russian draughts has no standard ELO-rated engine scale the way chess
# does — search depth is the actual knob, so difficulty maps to that
# instead. HARD (6) matches the pre-difficulty-selector default exactly.
_DIFFICULTY_DEPTH: dict[Difficulty, int] = {
    Difficulty.VERY_EASY: 1,
    Difficulty.EASY: 2,
    Difficulty.EASY_PLUS: 3,
    Difficulty.MEDIUM: 4,
    Difficulty.MEDIUM_PLUS: 5,
    Difficulty.HARD: 6,
    Difficulty.HARD_PLUS: 7,
    Difficulty.VERY_HARD: 9,
    Difficulty.VERY_HARD_PLUS: 10,
    Difficulty.IMPOSSIBLE: 12,
}


@dataclass
class CheckersSession:
    board: draughts.RussianBoard
    engine: draughts.SimpleEngine


def start(difficulty: Difficulty | None = None) -> CheckersSession:
    depth = _DIFFICULTY_DEPTH[difficulty] if difficulty is not None else _ENGINE_DEPTH
    return CheckersSession(board=draughts.RussianBoard(), engine=draughts.SimpleEngine(depth_limit=depth))


def legal_move_labels(session: CheckersSession) -> list[str]:
    """Numbered-square notation ("31-27") — the standard notation for
    Russian draughts, and what the AI move-resolver is handed as
    candidates (see modules.board_games.service_layer.resolve_player_move,
    same shape as chess_adapter.legal_move_labels)."""
    return [str(move) for move in session.board.legal_moves]


def legal_moves_with_squares(session: CheckersSession) -> list[tuple[str, str, str]]:
    """(from_square, to_square, label) for every legal move — same shape as
    chess_adapter's, using the numbers already embedded in the move's own
    label ("31-27", or a multi-hop capture like "23x14x5") since Russian
    draughts notation already names every square unambiguously; only the
    first and last matter for "which piece is this, and where can it end
    up" purposes."""
    result: list[tuple[str, str, str]] = []
    for move in session.board.legal_moves:
        label = str(move)
        squares = re.findall(r"\d+", label)
        result.append((squares[0], squares[-1], label))
    return result


def apply_player_move(session: CheckersSession, notation: str) -> MoveJudgement:
    """`notation` must already be one of legal_move_labels' output.
    Deliberately never calls SimpleEngine.evaluate() directly — that
    method crashes on RussianBoard (it's sized for a different board
    variant's square count internally; confirmed empirically, not
    documented) — get_best_move(..., with_evaluation=True) is the only
    evaluation path that actually works for this variant, so it's used
    for both the before- and after-move readings."""
    best_move, eval_before = session.engine.get_best_move(session.board, with_evaluation=True)
    best_label = str(best_move)

    session.board.push_uci(notation)

    if session.board.game_over:
        return MoveJudgement(notation=notation, was_mistake=False)

    _, eval_after_raw = session.engine.get_best_move(session.board, with_evaluation=True)
    eval_after = -eval_after_raw

    delta = eval_before - eval_after
    was_mistake = delta > _MISTAKE_THRESHOLD and best_label != notation
    return MoveJudgement(
        notation=notation,
        was_mistake=was_mistake,
        better_move=best_label if was_mistake else None,
        eval_delta=float(delta) if was_mistake else None,
    )


def apply_engine_move(session: CheckersSession) -> EngineMove:
    move, _ = session.engine.get_best_move(session.board, with_evaluation=True)
    label = str(move)
    squares = re.findall(r"\d+", label)
    session.board.push(move)
    return EngineMove(notation=label, from_square=squares[0], to_square=squares[-1])


def is_over(session: CheckersSession) -> bool:
    return session.board.game_over


def result_string(session: CheckersSession) -> str:
    """"1-0" / "0-1" / "1/2-1/2" for a finished game, "-" while ongoing —
    almost the same convention chess_adapter.result_string uses (that one
    returns "*" for ongoing instead of "-"), so
    modules.board_games.announce.result_text checks for both rather than
    assuming they're identical."""
    return session.board.result


def render_svg(session: CheckersSession) -> str:
    return draughts.svg.board(session.board, size=400)
