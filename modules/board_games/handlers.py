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

_GAME_LABELS: dict[GameKind, str] = {
    GameKind.CHESS: "Шахматы",
    GameKind.CHECKERS: "Шашки",
}
_GAME_BY_LABEL: dict[str, GameKind] = {label: kind for kind, label in _GAME_LABELS.items()}


async def _handle_start_board_game(params: dict[str, Any]) -> dict[str, Any]:
    label = params.get("game", _GAME_LABELS[GameKind.CHESS])
    kind = _GAME_BY_LABEL.get(label, GameKind.CHESS)
    await asyncio.to_thread(ui_session.start, kind)
    noun = "шахматы" if kind is GameKind.CHESS else "шашки"
    return {"message": f"Партия в {noun} начата — доска на вкладке «Ассистент»."}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "start_board_game",
        _handle_start_board_game,
        dangerous=False,
        description="Начать новую партию (шахматы или шашки) против движка — игрок всегда ходит первым.",
    )
