from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

Direction = Literal["en_ru", "ru_en"]

_PARENTHETICAL = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_NON_WORD = re.compile(r"[^\w\s'-]+")
_SPACES = re.compile(r"\s+")
_EN_PREFIXES: tuple[str, ...] = ("to ", "a ", "an ", "the ")
SHORT_WORD_MAX_LETTERS = 6


@dataclass(frozen=True)
class CheckResult:
    correct: bool
    exact: bool
    matched: str | None


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFC", text).lower().replace("ё", "е")
    folded = _PARENTHETICAL.sub(" ", folded)
    folded = _NON_WORD.sub(" ", folded)
    return _SPACES.sub(" ", folded).strip(" -'")


def _strip_english_prefix(text: str) -> str:
    for prefix in _EN_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


def levenshtein(left: str, right: str, limit: int | None = None) -> int:
    if left == right:
        return 0
    if len(left) < len(right):
        left, right = right, left
    if limit is not None and len(left) - len(right) > limit:
        return limit + 1
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (left_char != right_char)))
        if limit is not None and min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


def allowed_typos(expected: str) -> int:
    letters = sum(1 for char in expected if char.isalpha())
    return 1 if letters <= SHORT_WORD_MAX_LETTERS else 2


def _variants(values: Iterable[str], direction: Direction) -> list[str]:
    variants: list[str] = []
    for value in values:
        for part in re.split(r"[;,/]", value):
            normalized = normalize(part)
            if direction == "ru_en":
                normalized = _strip_english_prefix(normalized)
            if normalized and normalized not in variants:
                variants.append(normalized)
    return variants


def check_answer(
    answer: str,
    accepted: Iterable[str],
    direction: Direction,
    *,
    lemma: str | None = None,
    lemmatize: Callable[[str], str] | None = None,
) -> CheckResult:
    given = normalize(answer)
    if direction == "ru_en":
        given = _strip_english_prefix(given)
    if not given:
        return CheckResult(correct=False, exact=False, matched=None)
    variants = _variants(accepted, direction)
    if given in variants:
        return CheckResult(correct=True, exact=True, matched=given)
    if direction == "ru_en" and lemma and lemmatize is not None:
        target = normalize(lemma)
        if lemmatize(given) == target:
            return CheckResult(correct=True, exact=True, matched=target)
    best: tuple[int, str] | None = None
    for variant in variants:
        limit = allowed_typos(variant)
        distance = levenshtein(given, variant, limit)
        if distance <= limit and (best is None or distance < best[0]):
            best = (distance, variant)
    if best is not None:
        return CheckResult(correct=True, exact=False, matched=best[1])
    return CheckResult(correct=False, exact=False, matched=None)
