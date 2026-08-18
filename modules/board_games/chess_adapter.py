from __future__ import annotations

import os
from dataclasses import dataclass

import chess
import chess.engine
import chess.svg

from core.logger import get_logger
from modules.board_games.domain import Difficulty, EngineMove, MoveJudgement

logger = get_logger(__name__)

# The system `stockfish` binary (see README's system packages list) — not a
# pip package, chess.engine talks to it over UCI via a subprocess. On
# Windows, a packaged install's winget-installed Stockfish isn't guaranteed
# to be on PATH (see frontend/electron/setup.ts's
# findWindowsStockfishAfterInstall) — in that case Electron passes the
# resolved absolute path via this env var instead of relying on PATH.
_ENGINE_COMMAND = os.environ.get("ASSISTANT_STOCKFISH_PATH", "stockfish")
_ANALYSIS_TIME_SECONDS = 0.5
# Centipawns — a pawn is ~100, so this is "gave up roughly a pawn's worth
# of advantage or more," a reasonable bar for "this specific move was a
# real mistake" without flagging every merely-imperfect move.
_MISTAKE_THRESHOLD_CENTIPAWNS = 100
_MATE_SCORE = 100_000

# Stockfish's own UCI_Elo range (confirmed via `echo uci | stockfish`: "option
# name UCI_Elo type spin default 1320 min 1320 max 3190") — "очень легко"
# can't go below what Stockfish itself supports weakening to.
_DIFFICULTY_ELO: dict[Difficulty, int] = {
    Difficulty.VERY_EASY: 1320,
    Difficulty.EASY: 1500,
    Difficulty.MEDIUM: 1800,
    Difficulty.HARD: 2200,
    Difficulty.VERY_HARD: 2700,
    Difficulty.IMPOSSIBLE: 3190,
}


@dataclass
class ChessSession:
    board: chess.Board
    engine: chess.engine.SimpleEngine


def start(difficulty: Difficulty | None = None) -> ChessSession:
    engine = chess.engine.SimpleEngine.popen_uci(_ENGINE_COMMAND)
    if difficulty is not None:
        engine.configure({"UCI_LimitStrength": True, "UCI_Elo": _DIFFICULTY_ELO[difficulty]})
    return ChessSession(board=chess.Board(), engine=engine)


def close(session: ChessSession) -> None:
    session.engine.quit()


def legal_move_labels(session: ChessSession) -> list[str]:
    """SAN notation for every legal move in the current position — the
    candidate list handed to the AI move-resolver (see
    modules.board_games.service_layer.resolve_player_move), same
    "numbered candidates, let the model pick one" shape already used by
    modules.ui_automation.grounding/modules.app_catalog.resolver/
    modules.task_orchestrator.planner."""
    return [session.board.san(move) for move in session.board.legal_moves]


def legal_moves_with_squares(session: ChessSession) -> list[tuple[str, str, str]]:
    """(from_square, to_square, SAN label) for every legal move — lets the
    UI group moves by origin square ("click a piece, see its legal
    destinations") without parsing SAN itself, which doesn't reliably
    encode the origin square (e.g. "e4" alone doesn't say the pawn started
    on e2)."""
    return [
        (chess.square_name(move.from_square), chess.square_name(move.to_square), session.board.san(move))
        for move in session.board.legal_moves
    ]


def _relative_eval_centipawns(session: ChessSession) -> int:
    """Score from the *side to move*'s own perspective — positive is good
    for whoever is about to move next, matching python-chess's own
    PovScore.relative convention."""
    info = session.engine.analyse(session.board, chess.engine.Limit(time=_ANALYSIS_TIME_SECONDS))
    return info["score"].relative.score(mate_score=_MATE_SCORE)


def apply_player_move(session: ChessSession, san: str) -> MoveJudgement:
    """`san` must already be one of legal_move_labels' output — this
    doesn't re-validate legality itself. Judges the move by comparing the
    position's eval immediately before it (i.e. how good the engine's own
    top choice was) against the eval right after playing `san` instead
    (negated, since it's now the opponent's turn to move — a good move for
    them is bad for whoever just moved)."""
    eval_before = _relative_eval_centipawns(session)
    best_result = session.engine.play(session.board, chess.engine.Limit(time=_ANALYSIS_TIME_SECONDS))
    engine_best_san = session.board.san(best_result.move)

    session.board.push_san(san)

    if session.board.is_game_over():
        # A finished position isn't worth (and may not be safe to) hand
        # back to the engine for another analyse() call — the move that
        # ends the game is never flagged as a mistake regardless of eval.
        return MoveJudgement(notation=san, was_mistake=False)

    eval_after = -_relative_eval_centipawns(session)
    delta = eval_before - eval_after
    was_mistake = delta > _MISTAKE_THRESHOLD_CENTIPAWNS and engine_best_san != san
    return MoveJudgement(
        notation=san,
        was_mistake=was_mistake,
        better_move=engine_best_san if was_mistake else None,
        eval_delta=float(delta) if was_mistake else None,
    )


def apply_engine_move(session: ChessSession) -> EngineMove:
    result = session.engine.play(session.board, chess.engine.Limit(time=_ANALYSIS_TIME_SECONDS))
    san = session.board.san(result.move)
    from_square = chess.square_name(result.move.from_square)
    to_square = chess.square_name(result.move.to_square)
    session.board.push(result.move)
    return EngineMove(notation=san, from_square=from_square, to_square=to_square)


def is_over(session: ChessSession) -> bool:
    return session.board.is_game_over()


def is_check(session: ChessSession) -> bool:
    return session.board.is_check()


def result_string(session: ChessSession) -> str:
    """PGN-style: "1-0" | "0-1" | "1/2-1/2" | "*" (ongoing) — see
    modules.board_games.announce.result_text, which turns this (plus
    which side the player is on) into spoken Russian. Shared convention
    with checkers_adapter.result_string, which returns the exact same
    strings for the equivalent outcomes."""
    return session.board.result()


def render_svg(session: ChessSession) -> str:
    """The current (typically final) board position, with the last move
    played highlighted — python-chess's own `lastmove` param, no manual
    square/arrow bookkeeping needed. Mistake feedback itself is spoken
    (see modules.board_games.announce), not drawn on this board — a
    single final position can't sensibly show arrows for mistakes made
    several moves ago, since the pieces have since moved."""
    lastmove = session.board.peek() if session.board.move_stack else None
    return chess.svg.board(session.board, size=400, lastmove=lastmove, check=session.board.king(session.board.turn) if session.board.is_check() else None)
