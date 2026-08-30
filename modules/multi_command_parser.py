from __future__ import annotations

import re

# Clause-level separators that almost always mark a genuine boundary between
# two spoken commands. "и"/"і"/"and" are far more collision-prone (they occur
# inside single commands: "туда и обратно", "мама и папа", "громче и ярче"),
# so a split on one of them only survives when every resulting fragment
# clears the structural guards in split_commands below.
_HARD_SEPARATORS: dict[str, tuple[str, ...]] = {
    "ru": ("а потом", "а затем", "после этого", "после чего", "потом", "затем", "дальше", "далее"),
    "uk": ("а потім", "після цього", "потім", "тоді", "далі"),
    "en": ("and then", "after that", "then", "next"),
}
_SOFT_SEPARATORS: dict[str, tuple[str, ...]] = {
    "ru": ("и",),
    "uk": ("і", "й", "та"),
    "en": ("and",),
}

# A fragment shorter than this (in words) is treated as a tail of the
# previous command ("выключи свет и музыку" — "музыку" is not its own
# command), which collapses the whole utterance back to one command.
_MIN_FRAGMENT_WORDS = 2

_LEADING_CONNECTIVES: dict[str, tuple[str, ...]] = {
    "ru": ("а", "и", "потом", "затем", "далее", "дальше", "ещё", "еще"),
    "uk": ("а", "і", "й", "та", "потім", "тоді", "далі"),
    "en": ("and", "then", "next", "also"),
}

_STRIP_CHARS = " \t\n,.;:!?"


def _ordered_alternatives(*groups: tuple[str, ...]) -> list[str]:
    """Longest phrase (by word count, then character length) first — Python's
    re alternation is first-match, not longest-match, so "а потом" must be
    tried before "потом" or the leading "а" is left dangling on the previous
    fragment."""
    seen: list[str] = []
    for group in groups:
        seen.extend(group)
    return sorted(set(seen), key=lambda phrase: (-len(phrase.split()), -len(phrase)))


def _build_pattern(language: str) -> re.Pattern[str]:
    hard = _HARD_SEPARATORS.get(language, _HARD_SEPARATORS["ru"])
    soft = _SOFT_SEPARATORS.get(language, _SOFT_SEPARATORS["ru"])
    alternatives = "|".join(re.escape(phrase) for phrase in _ordered_alternatives(hard, soft))
    # A comma splits on its own; a word separator only splits when framed by
    # whitespace, so it never fires inside a longer word ("иди", "andrew").
    return re.compile(rf"\s*,\s*|\s+(?:{alternatives})\s+", re.IGNORECASE)


def _strip_connective(fragment: str, language: str) -> str:
    connectives = _LEADING_CONNECTIVES.get(language, _LEADING_CONNECTIVES["ru"])
    words = fragment.split()
    while len(words) > 1 and words[0].strip(_STRIP_CHARS).lower() in connectives:
        words = words[1:]
    while len(words) > 1 and words[-1].strip(_STRIP_CHARS).lower() in connectives:
        words = words[:-1]
    return " ".join(words)


def split_commands(text: str, language: str) -> list[str]:
    """Splits a single utterance into the several commands it chains together
    ("выключи свет и поставь музыку"), or returns [text] unchanged when it
    holds at most one command. Deliberately conservative — see the guards
    below; the caller applies its own semantic guard (a whole-utterance
    custom-command / interpret() match) before ever looping over the result."""
    stripped = text.strip()
    if not stripped:
        return [stripped]

    raw_parts = [
        part.strip(_STRIP_CHARS)
        for part in _build_pattern(language).split(stripped)
        if part and part.strip(_STRIP_CHARS)
    ]
    if len(raw_parts) < 2:
        return [stripped]

    parts = [cleaned for cleaned in (_strip_connective(part, language) for part in raw_parts) if cleaned]
    if len(parts) < 2:
        return [stripped]
    if any(len(part.split()) < _MIN_FRAGMENT_WORDS for part in parts):
        return [stripped]

    return parts
