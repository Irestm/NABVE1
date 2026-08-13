from __future__ import annotations

import shutil
from types import SimpleNamespace

import chess
import pytest

from modules.board_games import chess_adapter
from modules.board_games.chess_adapter import ChessSession

_STOCKFISH_AVAILABLE = shutil.which("stockfish") is not None

# Methods below only touch session.board, never session.engine — exercising
# them doesn't need a real Stockfish subprocess, so `engine` is left
# deliberately unset (None) rather than skipped whenever the system binary
# isn't installed (see README's system packages list).


def _session(board: chess.Board | None = None) -> ChessSession:
    return ChessSession(board=board or chess.Board(), engine=None)  # type: ignore[arg-type]


def test_legal_move_labels_lists_all_opening_moves() -> None:
    labels = chess_adapter.legal_move_labels(_session())
    assert len(labels) == 20  # standard chess opening: 20 legal first moves
    assert "e4" in labels
    assert "Nf3" in labels


def test_is_over_false_for_opening_position() -> None:
    assert not chess_adapter.is_over(_session())


def test_is_check_false_for_opening_position() -> None:
    assert not chess_adapter.is_check(_session())


def test_result_string_ongoing_is_asterisk() -> None:
    assert chess_adapter.result_string(_session()) == "*"


def test_render_svg_returns_svg_markup() -> None:
    svg = chess_adapter.render_svg(_session())
    assert svg.startswith("<svg")


def test_render_svg_highlights_lastmove_after_a_push() -> None:
    board = chess.Board()
    board.push_san("e4")
    svg = chess_adapter.render_svg(_session(board))
    # python-chess renders lastmove-highlighted squares with this fill —
    # a cheap way to confirm `lastmove=` was actually passed through.
    assert "lastmove" in svg or "fill:#cdd16a" in svg or "e4" in svg


class _FakePlayResult:
    def __init__(self, move: chess.Move) -> None:
        self.move = move


def _fake_engine_returning(move_uci: str) -> SimpleNamespace:
    return SimpleNamespace(play=lambda board, limit: _FakePlayResult(chess.Move.from_uci(move_uci)))


def test_apply_player_move_flags_a_real_mistake(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session()
    session.engine = _fake_engine_returning("e2e4")  # engine "wants" e4 instead

    evals = iter([200, 200])  # eval_before=200; eval_after_raw=200 -> eval_after=-200
    monkeypatch.setattr(chess_adapter, "_relative_eval_centipawns", lambda s: next(evals))

    judgement = chess_adapter.apply_player_move(session, "a3")  # a deliberately passive move

    assert judgement.notation == "a3"
    assert judgement.was_mistake is True
    assert judgement.better_move == "e4"
    assert judgement.eval_delta == 400.0


def test_apply_player_move_not_a_mistake_when_delta_is_small(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session()
    session.engine = _fake_engine_returning("e2e4")

    evals = iter([50, 50])  # delta = 50 - (-50) = 100, not > threshold (100)
    monkeypatch.setattr(chess_adapter, "_relative_eval_centipawns", lambda s: next(evals))

    judgement = chess_adapter.apply_player_move(session, "a3")

    assert judgement.was_mistake is False
    assert judgement.better_move is None
    assert judgement.eval_delta is None


def test_apply_player_move_not_a_mistake_when_engine_agrees(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session()
    session.engine = _fake_engine_returning("e2e4")  # engine's own top choice

    evals = iter([500, 500])  # huge delta, but the player played the engine's own move
    monkeypatch.setattr(chess_adapter, "_relative_eval_centipawns", lambda s: next(evals))

    judgement = chess_adapter.apply_player_move(session, "e4")

    assert judgement.was_mistake is False


def test_apply_player_move_short_circuits_on_checkmate(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fool's mate: the mating move ends the game, so a finished position is
    # never handed back to the engine for a second eval() call — this must
    # not even call _relative_eval_centipawns a second time.
    board = chess.Board()
    for san in ("f3", "e5", "g4"):
        board.push_san(san)
    session = _session(board)
    session.engine = _fake_engine_returning("b1c3")  # any legal move in this position

    calls = {"n": 0}

    def _fake_eval(_session: ChessSession) -> int:
        calls["n"] += 1
        return 0

    monkeypatch.setattr(chess_adapter, "_relative_eval_centipawns", _fake_eval)

    judgement = chess_adapter.apply_player_move(session, "Qh4#")

    assert judgement.was_mistake is False
    assert judgement.better_move is None
    assert calls["n"] == 1  # only the before-move eval, never an after-move one
    assert chess_adapter.is_over(session)


@pytest.mark.skipif(not _STOCKFISH_AVAILABLE, reason="requires the system stockfish binary")
def test_real_stockfish_engine_start_and_play_a_move() -> None:
    session = chess_adapter.start()
    try:
        san = chess_adapter.apply_engine_move(session)
        assert san in [
            "a3", "a4", "b3", "b4", "c3", "c4", "d3", "d4", "e3", "e4", "f3", "f4",
            "g3", "g4", "h3", "h4", "Na3", "Nc3", "Nf3", "Nh3",
        ]
        assert len(session.board.move_stack) == 1
    finally:
        chess_adapter.close(session)
