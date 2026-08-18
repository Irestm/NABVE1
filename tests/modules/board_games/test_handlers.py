from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.dispatcher import CommandDispatcher
from modules.board_games import handlers, ui_session
from modules.board_games.domain import GameKind


def test_register_commands_registers_both_games() -> None:
    dispatcher = CommandDispatcher()

    handlers.register_commands(dispatcher)

    names = {c.name for c in dispatcher.list_commands()}
    assert {"start_chess_game", "start_checkers_game"} <= names


@pytest.mark.asyncio
async def test_handle_start_checkers_game_starts_a_session(monkeypatch: pytest.MonkeyPatch) -> None:
    started = MagicMock()
    monkeypatch.setattr(ui_session, "start", started)

    result = await handlers._handle_start_checkers_game({})

    started.assert_called_once_with(GameKind.CHECKERS)
    assert "message" in result


@pytest.mark.asyncio
async def test_handle_start_chess_game_starts_a_session(monkeypatch: pytest.MonkeyPatch) -> None:
    started = MagicMock()
    monkeypatch.setattr(ui_session, "start", started)

    result = await handlers._handle_start_chess_game({})

    started.assert_called_once_with(GameKind.CHESS)
    assert "message" in result
