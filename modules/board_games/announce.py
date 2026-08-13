from __future__ import annotations

from modules.board_games.domain import GameKind, MoveJudgement

# The player always moves first (see modules.board_games.service_layer's
# module docstring for why this first slice doesn't offer a color/side
# choice) — so "1-0" always means the player won, "0-1" always means NABVE
# won, regardless of which game. "*" (chess) and "-" (checkers) both mean
# "still in progress" — see checkers_adapter.result_string's own docstring
# for why they differ between the two libraries.
_ONGOING_RESULTS = {"*", "-"}

GAME_NAME: dict[GameKind, str] = {
    GameKind.CHESS: "шахматы",
    GameKind.CHECKERS: "шашки",
}


def which_game_prompt() -> str:
    return "Во что сыграем: в шахматы или в шашки?"


def game_started_text(kind: GameKind) -> str:
    return f"Начинаем партию в {GAME_NAME[kind]}. Вы ходите первым — назовите ваш ход."


def your_turn_prompt() -> str:
    return "Ваш ход."


def engine_move_text(notation: str) -> str:
    return f"Хожу: {notation}."


def check_text() -> str:
    return "Шах."


def move_not_understood_text() -> str:
    return "Не поняла, какой ход вы имеете в виду. Повторите, пожалуйста."


def game_stopped_text() -> str:
    return "Партия остановлена."


def result_text(result_string: str) -> str:
    if result_string in _ONGOING_RESULTS:
        return "Партия ещё не закончена."
    if result_string == "1-0":
        return "Партия окончена. Вы выиграли!"
    if result_string == "0-1":
        return "Партия окончена. Победа за мной."
    return "Партия окончена. Ничья."


def mistake_text(judgement: MoveJudgement) -> str:
    assert judgement.was_mistake and judgement.better_move is not None
    return f"На ходе {judgement.notation} лучше было бы сыграть {judgement.better_move}."


def summary_intro_text(mistake_count: int) -> str:
    if mistake_count == 0:
        return "Разбор партии: ошибок не нашла, хорошая игра."
    if mistake_count == 1:
        return "Разбор партии: нашла один ход, который можно было сыграть сильнее."
    return f"Разбор партии: нашла {mistake_count} ходов, которые можно было сыграть сильнее."
