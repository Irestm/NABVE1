from __future__ import annotations

from modules.hardware_adaptive.local_ai import is_complex_query


def test_short_ordinary_question_is_not_complex() -> None:
    assert not is_complex_query("как меня зовут")


def test_long_ordinary_text_without_a_marker_is_not_complex() -> None:
    # Regression: a length threshold used to flag any sufficiently long text
    # as complex regardless of content, which routed ordinary long-but-not-
    # live-data questions away from the user's own configured API key for
    # no good reason. Marker presence is now the only signal.
    assert not is_complex_query("а" * 500)


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
