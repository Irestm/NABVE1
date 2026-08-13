from __future__ import annotations

import draughts
import pytest

from modules.board_games import checkers_adapter
from modules.board_games.checkers_adapter import CheckersSession


class _FakeMove:
    def __init__(self, label: str) -> None:
        self._label = label

    def __str__(self) -> str:  # noqa: D105 - trivial
        return self._label


class _QueueEngine:
    """Returns pre-scripted (move, evaluation) pairs in order — lets tests
    force specific eval sequences without depending on py-draughts's real
    (symmetric, in the opening) SimpleEngine evaluations."""

    def __init__(self, replies: list[tuple[str, float]]) -> None:
        self._replies = list(replies)

    def get_best_move(self, board: object, with_evaluation: bool = True) -> tuple[_FakeMove, float]:
        label, ev = self._replies.pop(0)
        return _FakeMove(label), ev


class _FakeBoard:
    """Stands in for draughts.RussianBoard for tests that only need
    push_uci/game_over — see apply_player_move's checkmate/game-over
    short-circuit test below."""

    def __init__(self, game_over: bool) -> None:
        self.game_over = game_over
        self.pushed: list[str] = []

    def push_uci(self, notation: str) -> None:
        self.pushed.append(notation)


def _real_session() -> CheckersSession:
    return CheckersSession(board=draughts.RussianBoard(), engine=draughts.SimpleEngine(depth_limit=4))


# --- real py-draughts integration (pure Python, no system binary needed) ---


def test_legal_move_labels_lists_opening_moves() -> None:
    labels = checkers_adapter.legal_move_labels(_real_session())
    assert len(labels) == 7  # standard Russian draughts opening: 7 legal first moves
    assert "24-19" in labels


def test_is_over_false_for_opening_position() -> None:
    assert not checkers_adapter.is_over(_real_session())


def test_result_string_ongoing_is_dash() -> None:
    assert checkers_adapter.result_string(_real_session()) == "-"


def test_render_svg_returns_svg_markup() -> None:
    assert checkers_adapter.render_svg(_real_session()).startswith("<svg")


def test_apply_engine_move_plays_a_legal_move_and_advances_the_board() -> None:
    session = _real_session()
    before = checkers_adapter.legal_move_labels(session)
    label = checkers_adapter.apply_engine_move(session)
    assert label in before
    assert not checkers_adapter.is_over(session)  # one move never ends the opening


# --- apply_player_move mistake-detection arithmetic (fake engine, real board) --


def test_apply_player_move_flags_a_real_mistake() -> None:
    board = draughts.RussianBoard()
    played = str(next(iter(board.legal_moves)))
    session = CheckersSession(board=board, engine=_QueueEngine([("99-99", 2.0), ("11-11", 2.0)]))

    judgement = checkers_adapter.apply_player_move(session, played)

    # eval_before=2.0; eval_after = -2.0 (negated after-move reading);
    # delta = 2.0 - (-2.0) = 4.0 > threshold, and the engine's pick ("99-99")
    # differs from what was actually played.
    assert judgement.was_mistake is True
    assert judgement.better_move == "99-99"
    assert judgement.eval_delta == pytest.approx(4.0)


def test_apply_player_move_not_a_mistake_when_delta_is_small() -> None:
    board = draughts.RussianBoard()
    played = str(next(iter(board.legal_moves)))
    session = CheckersSession(board=board, engine=_QueueEngine([("99-99", 0.1), ("11-11", 0.1)]))

    judgement = checkers_adapter.apply_player_move(session, played)

    assert judgement.was_mistake is False
    assert judgement.better_move is None
    assert judgement.eval_delta is None


def test_apply_player_move_not_a_mistake_when_engine_agrees() -> None:
    board = draughts.RussianBoard()
    played = str(next(iter(board.legal_moves)))
    # Engine's own top pick is exactly what was played, despite a big delta.
    session = CheckersSession(board=board, engine=_QueueEngine([(played, 5.0), ("11-11", 5.0)]))

    judgement = checkers_adapter.apply_player_move(session, played)

    assert judgement.was_mistake is False


def test_apply_player_move_short_circuits_when_game_ends() -> None:
    session = CheckersSession(board=_FakeBoard(game_over=True), engine=_QueueEngine([("99-99", 1.0)]))

    judgement = checkers_adapter.apply_player_move(session, "31-27")

    assert judgement.notation == "31-27"
    assert judgement.was_mistake is False
    assert session.board.pushed == ["31-27"]  # the move itself was still applied
