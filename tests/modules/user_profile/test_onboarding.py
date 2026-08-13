from __future__ import annotations

from modules.user_profile.onboarding import _match_label, _match_labels, _voice_short_name

_STYLE_LABELS = [
    "Вежливо", "Приземлённо", "Агрессивно", "Спокойно", "С матами",
    "Дружелюбно", "Официально", "С юмором", "Философски",
]

# Regression coverage for the stop-word onboarding step: it reuses
# _match_label/_voice_short_name for nothing (it's a free-text answer, no
# fixed choices) - see test_pipeline_pause.py and test_wake_word.py for the
# behavior the stop word actually drives.


def test_match_label_exact() -> None:
    assert _match_label("Агрессивно", ["Вежливо", "Агрессивно", "Спокойно"]) == "Агрессивно"


def test_match_label_is_case_insensitive() -> None:
    assert _match_label("агрессивно", ["Вежливо", "Агрессивно", "Спокойно"]) == "Агрессивно"


def test_match_label_tolerates_stt_noise() -> None:
    # A trailing word a real STT pass might tack on shouldn't break the match.
    assert _match_label("агрессивно пожалуйста", ["Вежливо", "Агрессивно", "Спокойно"]) == "Агрессивно"


def test_match_label_returns_none_for_empty_answer() -> None:
    assert _match_label("", ["Вежливо", "Агрессивно"]) is None
    assert _match_label("   ", ["Вежливо", "Агрессивно"]) is None


def test_match_label_returns_none_when_nothing_close_enough() -> None:
    assert _match_label("совершенно другое слово", ["Айдар", "Байя", "Ксения"]) is None


def test_voice_short_name_strips_parenthetical() -> None:
    assert _voice_short_name("Ксения (Xenia)") == "Ксения"
    assert _voice_short_name("Случайный (звучит по-разному каждый раз)") == "Случайный"
    assert _voice_short_name("Айдар") == "Айдар"


# --- _match_labels (multi-select, e.g. mixing communication-style traits) --


def test_match_labels_finds_two_traits_in_one_sentence() -> None:
    assert _match_labels("агрессивно и с юмором", _STYLE_LABELS, 3) == ["Агрессивно", "С юмором"]


def test_match_labels_finds_three_traits_and_respects_cap() -> None:
    result = _match_labels("агрессивно, с юмором и официально", _STYLE_LABELS, 3)
    assert set(result) == {"Агрессивно", "С юмором", "Официально"}
    assert len(result) == 3


def test_match_labels_caps_even_when_more_than_max_are_named() -> None:
    result = _match_labels("агрессивно, с юмором, официально и спокойно", _STYLE_LABELS, 3)
    assert len(result) == 3


def test_match_labels_single_word_answer_does_not_match_unrelated_traits() -> None:
    # Regression: a loose per-candidate threshold used to also "match"
    # unrelated labels (e.g. "Агрессивно", "Дружелюбно") against a short,
    # single-trait answer purely from incidental shared characters.
    assert _match_labels("вежливо", _STYLE_LABELS, 3) == ["Вежливо"]


def test_match_labels_returns_empty_for_empty_answer() -> None:
    assert _match_labels("", _STYLE_LABELS, 3) == []


def test_match_labels_returns_empty_when_nothing_matches() -> None:
    assert _match_labels("совершенно другой ответ без черт", _STYLE_LABELS, 3) == []
