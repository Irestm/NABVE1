from __future__ import annotations

import pytest

from modules.english_learning.answer_check import allowed_typos, check_answer, levenshtein, normalize


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("  Ёлка!! ", "елка"), ("понять (что-то)", "понять"), ("To  Decide.", "to decide"), ("Rock'n'roll", "rock'n'roll")],
)
def test_normalize(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


def test_levenshtein_with_limit() -> None:
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("kitten", "sitting", limit=1) == 2
    assert levenshtein("abc", "abcdef", limit=1) == 2


@pytest.mark.parametrize(("word", "typos"), [("кот", 1), ("решить", 1), ("разобраться", 2), ("figure out", 2)])
def test_allowed_typos(word: str, typos: int) -> None:
    assert allowed_typos(word) == typos


@pytest.mark.parametrize(
    ("given", "accepted", "correct"),
    [
        ("Понять", ["понять", "разобраться"], True),
        ("разобратся", ["понять", "разобраться"], True),
        ("разабратся", ["понять", "разобраться"], True),
        ("рзбрться", ["разобраться"], False),
        ("решитъ", ["решить"], True),
        ("решать", ["решить"], True),
        ("рашать", ["решить"], False),
        ("ещё", ["еще"], True),
        ("", ["решить"], False),
        ("честный", ["искренний; честный"], True),
    ],
)
def test_en_ru_fuzzy_rules(given: str, accepted: list[str], correct: bool) -> None:
    assert check_answer(given, accepted, "en_ru").correct is correct


def test_exact_flag_distinguishes_typos() -> None:
    assert check_answer("решить", ["решить"], "en_ru").exact is True
    assert check_answer("решитт", ["решить"], "en_ru").exact is False


def test_ru_en_accepts_lemma_forms_and_to_prefix() -> None:
    forms = {"decided": "decide", "deciding": "decide", "figured out": "figure out"}

    def lemmatize(text: str) -> str:
        return forms.get(text, text)

    assert check_answer("to decide", ["decide"], "ru_en").correct
    assert check_answer("Decided", ["decide"], "ru_en", lemma="decide", lemmatize=lemmatize).exact
    assert check_answer("figured out", ["figure out"], "ru_en", lemma="figure out", lemmatize=lemmatize).correct
    assert not check_answer("choose", ["decide"], "ru_en", lemma="decide", lemmatize=lemmatize).correct
