from __future__ import annotations

import asyncio
from typing import Any

from core.dispatcher import CommandDispatcher
from modules.board_games import ui_session
from modules.board_games.domain import GameKind

# Duplicate entry point for the same board-game UI section on the
# Ассистент tab (frontend/src/components/BoardGamesPanel.tsx) — lets
# CommandPanel's grid start a game too, not just the section itself or a
# spoken "сыграем в шахматы". Both paths call the same ui_session.start(),
# so whichever one the user reaches for, it's the same game state.


async def _handle_start_chess_game(_params: dict[str, Any]) -> dict[str, Any]:
    await asyncio.to_thread(ui_session.start, GameKind.CHESS)
    return {"message": "Партия в шахматы начата — доска на вкладке «Ассистент»."}


async def _handle_start_checkers_game(_params: dict[str, Any]) -> dict[str, Any]:
    await asyncio.to_thread(ui_session.start, GameKind.CHECKERS)
    return {"message": "Партия в шашки начата — доска на вкладке «Ассистент»."}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "start_chess_game",
        _handle_start_chess_game,
        dangerous=False,
        description="Начать новую партию в шахматы против движка — игрок всегда ходит первым.",
    )
    dispatcher.register(
        "start_checkers_game",
        _handle_start_checkers_game,
        dangerous=False,
        description="Начать новую партию в русские шашки против движка — игрок всегда ходит первым.",
    )
