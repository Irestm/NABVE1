from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.dispatcher import CommandDispatcher
from modules.board_games import handlers, ui_session
from modules.board_games.domain import GameKind


def test_register_commands_registers_start_board_game() -> None:
    dispatcher = CommandDispatcher()

    handlers.register_commands(dispatcher)

    names = {c.name for c in dispatcher.list_commands()}
    assert "start_board_game" in names


@pytest.mark.asyncio
async def test_handle_start_board_game_starts_checkers(monkeypatch: pytest.MonkeyPatch) -> None:
    started = MagicMock()
    monkeypatch.setattr(ui_session, "start", started)

    result = await handlers._handle_start_board_game({"game": "Шашки"})

    started.assert_called_once_with(GameKind.CHECKERS)
    assert "message" in result


@pytest.mark.asyncio
async def test_handle_start_board_game_starts_chess(monkeypatch: pytest.MonkeyPatch) -> None:
    started = MagicMock()
    monkeypatch.setattr(ui_session, "start", started)

    result = await handlers._handle_start_board_game({"game": "Шахматы"})

    started.assert_called_once_with(GameKind.CHESS)
    assert "message" in result


@pytest.mark.asyncio
async def test_handle_start_board_game_defaults_to_chess(monkeypatch: pytest.MonkeyPatch) -> None:
    started = MagicMock()
    monkeypatch.setattr(ui_session, "start", started)

    result = await handlers._handle_start_board_game({})

    started.assert_called_once_with(GameKind.CHESS)
    assert "message" in result
