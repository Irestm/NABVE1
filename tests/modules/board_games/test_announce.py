from __future__ import annotations

import pytest

from modules.board_games import announce
from modules.board_games.domain import GameKind, MoveJudgement


def test_game_started_text_names_the_game() -> None:
    assert "шахматы" in announce.game_started_text(GameKind.CHESS)
    assert "шашки" in announce.game_started_text(GameKind.CHECKERS)


def test_engine_move_text_includes_notation() -> None:
    assert "e2e4" in announce.engine_move_text("e2e4")


@pytest.mark.parametrize("ongoing_result", ["*", "-"])
def test_result_text_ongoing_for_both_libraries_conventions(ongoing_result: str) -> None:
    # chess_adapter uses "*" for ongoing, checkers_adapter uses "-" — both
    # must read as "not finished yet," not as a draw.
    assert announce.result_text(ongoing_result) == "Партия ещё не закончена."


def test_result_text_player_win() -> None:
    assert "выиграли" in announce.result_text("1-0")


def test_result_text_engine_win() -> None:
    assert "за мной" in announce.result_text("0-1")


def test_result_text_draw() -> None:
    assert "Ничья" in announce.result_text("1/2-1/2")


def test_mistake_text_includes_notation_and_better_move() -> None:
    judgement = MoveJudgement(notation="Qxb7", was_mistake=True, better_move="Nf3", eval_delta=250.0)
    text = announce.mistake_text(judgement)
    assert "Qxb7" in text
    assert "Nf3" in text


def test_mistake_text_asserts_on_non_mistake() -> None:
    judgement = MoveJudgement(notation="e4", was_mistake=False)
    with pytest.raises(AssertionError):
        announce.mistake_text(judgement)


def test_summary_intro_text_zero_mistakes_default_gender_is_male() -> None:
    assert "ошибок не нашёл" in announce.summary_intro_text(0)


def test_summary_intro_text_zero_mistakes_uses_female_form_when_gender_is_female(monkeypatch) -> None:
    monkeypatch.setattr(announce.gender_module, "get_user_gender", lambda: "female")

    assert "ошибок не нашла" in announce.summary_intro_text(0)


def test_summary_intro_text_one_mistake_uses_singular() -> None:
    assert "один ход" in announce.summary_intro_text(1)


def test_summary_intro_text_multiple_mistakes_includes_count() -> None:
    assert "3" in announce.summary_intro_text(3)
