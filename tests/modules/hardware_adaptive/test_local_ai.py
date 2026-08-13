from __future__ import annotations

from modules.hardware_adaptive.local_ai import is_complex_query


def test_short_ordinary_question_is_not_complex() -> None:
    assert not is_complex_query("как меня зовут")


def test_text_over_length_threshold_is_complex() -> None:
    assert is_complex_query("а" * 241)


def test_web_search_marker_is_complex() -> None:
    assert is_complex_query("погугли рецепт борща")


def test_news_marker_is_complex() -> None:
    assert is_complex_query("расскажи последние новости")


def test_live_data_markers_are_complex() -> None:
    assert is_complex_query("какой сейчас курс доллара")
    assert is_complex_query("какая погода сегодня в Киеве")
    assert is_complex_query("what's the weather today")


def test_marker_match_is_case_insensitive() -> None:
    assert is_complex_query("ПОГУГЛИ что-нибудь интересное")
