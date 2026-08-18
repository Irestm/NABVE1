from __future__ import annotations

import pytest

from modules.board_games import service_layer, ui_session
from modules.board_games.domain import GameKind


@pytest.fixture(autouse=True)
def _reset_current_session() -> None:
    # ui_session._current is module-level global state — tests must not
    # leak a started game (with a live Stockfish subprocess, for chess)
    # into the next test.
    ui_session._current = None
    yield
    if ui_session._current is not None:
        service_layer.finish(ui_session._current)
    ui_session._current = None


def test_current_is_none_before_any_game_started() -> None:
    assert ui_session.current() is None


def test_require_current_raises_before_any_game_started() -> None:
    with pytest.raises(RuntimeError, match="Игра ещё не начата"):
        ui_session.require_current()


def test_start_checkers_makes_it_the_current_session() -> None:
    session = ui_session.start(GameKind.CHECKERS)

    assert session.kind == GameKind.CHECKERS
    assert ui_session.current() is session
    assert ui_session.require_current() is session


def test_starting_a_second_game_replaces_and_finishes_the_first(monkeypatch: pytest.MonkeyPatch) -> None:
    finished_sessions = []
    real_finish = service_layer.finish

    def tracking_finish(session):
        finished_sessions.append(session)
        return real_finish(session)

    monkeypatch.setattr(service_layer, "finish", tracking_finish)

    first = ui_session.start(GameKind.CHECKERS)
    second = ui_session.start(GameKind.CHECKERS)

    assert finished_sessions == [first]
    assert ui_session.current() is second
    assert second is not first


def test_finish_clears_the_current_session_and_returns_a_summary() -> None:
    ui_session.start(GameKind.CHECKERS)

    summary = ui_session.finish()

    assert summary is not None
    assert summary.result_string == "-"
    assert ui_session.current() is None


def test_finish_with_no_active_game_returns_none() -> None:
    assert ui_session.finish() is None
