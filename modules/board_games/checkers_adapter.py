from __future__ import annotations

from dataclasses import dataclass

import draughts
import draughts.svg

from core.logger import get_logger
from modules.board_games.domain import MoveJudgement

logger = get_logger(__name__)

_ENGINE_DEPTH = 6
# SimpleEngine's own evaluation scale (roughly "material advantage in
# pieces"), not centipawns — not directly comparable to chess_adapter's
# threshold, this one was picked empirically against the same engine.
_MISTAKE_THRESHOLD = 1.0


@dataclass
class CheckersSession:
    board: draughts.RussianBoard
    engine: draughts.SimpleEngine


def start() -> CheckersSession:
    return CheckersSession(board=draughts.RussianBoard(), engine=draughts.SimpleEngine(depth_limit=_ENGINE_DEPTH))


def legal_move_labels(session: CheckersSession) -> list[str]:
    """Numbered-square notation ("31-27") — the standard notation for
    Russian draughts, and what the AI move-resolver is handed as
    candidates (see modules.board_games.service_layer.resolve_player_move,
    same shape as chess_adapter.legal_move_labels)."""
    return [str(move) for move in session.board.legal_moves]


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


def apply_engine_move(session: CheckersSession) -> str:
    move, _ = session.engine.get_best_move(session.board, with_evaluation=True)
    label = str(move)
    session.board.push(move)
    return label


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
