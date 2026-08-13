from __future__ import annotations

import asyncio

import chess
import draughts
import pytest

from modules.board_games import chess_adapter, service_layer
from modules.board_games.chess_adapter import ChessSession
from modules.board_games.checkers_adapter import CheckersSession
from modules.board_games.domain import GameKind, MoveJudgement
from modules.board_games.service_layer import GameSession


class _FakeAdapter:
    def __init__(self, name: str, reply: str) -> None:
        self.name = name
        self._reply = reply

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
        return self._reply


class _FailingAdapter:
    name = "failing"

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
        raise RuntimeError("boom")


def _checkers_game_session() -> GameSession:
    return GameSession(kind=GameKind.CHECKERS, inner=CheckersSession(board=draughts.RussianBoard(), engine=draughts.SimpleEngine(depth_limit=4)))


# --- start_game / legal_move_labels ----------------------------------------


def test_start_game_checkers_returns_a_playable_session() -> None:
    session = service_layer.start_game(GameKind.CHECKERS)
    assert session.kind == GameKind.CHECKERS
    assert len(service_layer.legal_move_labels(session)) == 7


# --- resolve_player_move -----------------------------------------------------


def test_resolve_player_move_matches_by_index(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _checkers_game_session()
    candidates = service_layer.legal_move_labels(session)
    adapter = _FakeAdapter("local", "2")
    monkeypatch.setattr(service_layer, "local_first_chain", lambda: [adapter])

    resolved = asyncio.run(service_layer.resolve_player_move(session, "какой-то ход"))

    assert resolved == candidates[2]


def test_resolve_player_move_returns_none_when_model_says_no(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _checkers_game_session()
    adapter = _FakeAdapter("local", "нет")
    monkeypatch.setattr(service_layer, "local_first_chain", lambda: [adapter])

    assert asyncio.run(service_layer.resolve_player_move(session, "непонятно что")) is None


def test_resolve_player_move_falls_through_a_failing_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _checkers_game_session()
    candidates = service_layer.legal_move_labels(session)
    working = _FakeAdapter("cloud", "0")
    monkeypatch.setattr(service_layer, "local_first_chain", lambda: [_FailingAdapter(), working])

    resolved = asyncio.run(service_layer.resolve_player_move(session, "первый ход"))

    assert resolved == candidates[0]


def test_resolve_player_move_returns_none_when_every_adapter_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _checkers_game_session()
    monkeypatch.setattr(service_layer, "local_first_chain", lambda: [_FailingAdapter()])

    assert asyncio.run(service_layer.resolve_player_move(session, "что угодно")) is None


# --- apply_player_move: mistake bookkeeping ---------------------------------


def test_apply_player_move_records_a_mistake_on_the_session(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _checkers_game_session()
    mistake = MoveJudgement(notation="24-19", was_mistake=True, better_move="23-18", eval_delta=4.0)
    monkeypatch.setattr(service_layer.checkers_adapter, "apply_player_move", lambda inner, notation: mistake)

    judgement = service_layer.apply_player_move(session, "24-19")

    assert judgement == mistake
    assert session.mistakes == [mistake]


def test_apply_player_move_does_not_record_a_non_mistake(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _checkers_game_session()
    fine_move = MoveJudgement(notation="24-19", was_mistake=False)
    monkeypatch.setattr(service_layer.checkers_adapter, "apply_player_move", lambda inner, notation: fine_move)

    service_layer.apply_player_move(session, "24-19")

    assert session.mistakes == []


# --- is_check: only chess has the concept -----------------------------------


def test_is_check_true_for_a_checked_chess_position() -> None:
    board = chess.Board()
    for san in ("e4", "e5", "Qh5", "Nc6", "Qxf7"):
        board.push_san(san)
    session = GameSession(kind=GameKind.CHESS, inner=ChessSession(board=board, engine=None))  # type: ignore[arg-type]

    assert service_layer.is_check(session)


def test_is_check_false_for_checkers_regardless_of_position() -> None:
    session = _checkers_game_session()
    assert not service_layer.is_check(session)


# --- finish ------------------------------------------------------------------


def test_finish_checkers_builds_summary_without_touching_chess_close(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"closed": False}
    monkeypatch.setattr(chess_adapter, "close", lambda inner: called.__setitem__("closed", True))

    session = _checkers_game_session()
    session.mistakes.append(MoveJudgement(notation="24-19", was_mistake=True, better_move="23-18", eval_delta=4.0))

    summary = service_layer.finish(session)

    assert summary.result_string == "-"
    assert summary.mistakes == tuple(session.mistakes)
    assert summary.board_svg.startswith("<svg")
    assert called["closed"] is False


def test_finish_chess_closes_the_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"closed": False}
    monkeypatch.setattr(chess_adapter, "close", lambda inner: called.__setitem__("closed", True))

    session = GameSession(kind=GameKind.CHESS, inner=ChessSession(board=chess.Board(), engine=None))  # type: ignore[arg-type]

    summary = service_layer.finish(session)

    assert summary.result_string == "*"
    assert called["closed"] is True
