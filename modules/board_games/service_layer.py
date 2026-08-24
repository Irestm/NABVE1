from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Union

from core.ai_adapter_chain import candidate_chain
from core.logger import get_logger
from modules.board_games import chess_adapter, checkers_adapter
from modules.board_games.domain import Difficulty, EngineMove, GameKind, GameSummary, MoveJudgement

logger = get_logger(__name__)

GAME_LABEL: dict[GameKind, str] = {GameKind.CHESS: "шахматы", GameKind.CHECKERS: "шашки"}

_InnerSession = Union[chess_adapter.ChessSession, checkers_adapter.CheckersSession]


@dataclass
class GameSession:
    """Held by modules.board_games.ui_session's module-level singleton
    across separate REST calls and separate voice turns alike — both the
    click-driven board (core/main.py's /api/boardgames/* + BoardGamesPanel.tsx)
    and the voice pipeline (core/voice/pipeline.py's _resolve_board_game /
    _resolve_active_board_game_utterance / _resolve_board_game_move) act on
    the exact same GameSession, so a move made either way shows up on the
    same board. One game at a time, by construction — see ui_session.start()."""

    kind: GameKind
    inner: _InnerSession
    mistakes: list[MoveJudgement] = field(default_factory=list)
    difficulty: Difficulty | None = None


def _adapter(kind: GameKind):
    return chess_adapter if kind == GameKind.CHESS else checkers_adapter


def start_game(kind: GameKind, difficulty: Difficulty | None = None) -> GameSession:
    inner = (
        chess_adapter.start(difficulty) if kind == GameKind.CHESS else checkers_adapter.start(difficulty)
    )
    return GameSession(kind=kind, inner=inner, difficulty=difficulty)


def legal_move_labels(session: GameSession) -> list[str]:
    return _adapter(session.kind).legal_move_labels(session.inner)


def legal_moves_with_squares(session: GameSession) -> list[tuple[str, str, str]]:
    return _adapter(session.kind).legal_moves_with_squares(session.inner)


def _parse_move_index(raw: str, count: int) -> int | None:
    match = re.search(r"\d+", raw)
    if not match:
        return None
    index = int(match.group(0))
    return index if 0 <= index < count else None


async def resolve_player_move(session: GameSession, spoken_text: str) -> str | None:
    """Matches `spoken_text` (already transcribed) against the current
    position's legal moves via an AI adapter — the same "numbered
    candidates, let the model pick one by index" shape already used by
    modules.ui_automation.grounding.ground, modules.app_catalog.resolver,
    and modules.task_orchestrator.planner. Returns the matched move's own
    notation string (SAN for chess, "31-27"-style for checkers — exactly
    what apply_player_move expects back), or None if nothing confidently
    matched (caller should ask the user to repeat, same as those three)."""
    candidates = legal_move_labels(session)
    if not candidates:
        return None

    listing = "; ".join(f"{i}: {label}" for i, label in enumerate(candidates))
    prompt = (
        f'Пользователь голосом назвал ход в партии в {GAME_LABEL[session.kind]}: "{spoken_text}". '
        f"Вот пронумерованный список ходов, легальных в текущей позиции: {listing}. "
        "Определи, какой из них имел в виду пользователь, по номеру. Ответь ТОЛЬКО числом — "
        'номером хода из списка, ничем больше. Если ни один вариант явно не подходит — ответь "нет".'
    )
    for adapter in candidate_chain(spoken_text):
        try:
            raw = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            logger.warning("Move resolution adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue
        index = _parse_move_index(raw, len(candidates))
        if index is not None:
            return candidates[index]

    return None


def apply_player_move(session: GameSession, notation: str) -> MoveJudgement:
    judgement = _adapter(session.kind).apply_player_move(session.inner, notation)
    if judgement.was_mistake:
        session.mistakes.append(judgement)
    return judgement


def apply_engine_move(session: GameSession) -> EngineMove:
    return _adapter(session.kind).apply_engine_move(session.inner)


def is_over(session: GameSession) -> bool:
    return _adapter(session.kind).is_over(session.inner)


def render_svg(session: GameSession) -> str:
    """The current board position as SVG — safe to call any time, not just
    at finish() (which also calls this, for the final position); the UI
    board (core/main.py's /api/boardgames/* endpoints) calls this after
    every move to keep the on-screen board in sync."""
    return _adapter(session.kind).render_svg(session.inner)


def result_string(session: GameSession) -> str:
    return _adapter(session.kind).result_string(session.inner)


def is_check(session: GameSession) -> bool:
    # Only chess has a "check" concept the player benefits from hearing
    # called out mid-game; draughts has no equivalent.
    return session.kind == GameKind.CHESS and chess_adapter.is_check(session.inner)


def finish(session: GameSession) -> GameSummary:
    """Ends the session (releases the chess engine subprocess, if any) and
    builds the final summary — called exactly once, when the game is over
    or the player stopped it early."""
    adapter = _adapter(session.kind)
    result_string = adapter.result_string(session.inner)
    board_svg = adapter.render_svg(session.inner)
    if session.kind == GameKind.CHESS:
        chess_adapter.close(session.inner)
    return GameSummary(result_string=result_string, mistakes=tuple(session.mistakes), board_svg=board_svg)
