from __future__ import annotations

import re
from dataclasses import dataclass

# Deliberately rule-based (same style as core/voice/intent.py), not another
# AI round-trip: this runs on every single command utterance, so it needs
# to be fast, local, and independent of ai_bridge's browser-automated
# providers (which the logs show failing periodically on selector
# changes). It will miss facts phrased differently — that's an accepted
# trade-off, documented as an extension point rather than a requirement to
# catch everything. See modules/user_profile/service_layer.record_episodic_fact
# for what happens to what this does catch (bounded, forgotten if unused).


@dataclass(frozen=True)
class ExtractedFact:
    key: str
    value: str


# Non-greedy capture stopping at sentence punctuation or a clause-joining
# conjunction, so "меня зовут Даниил и я живу в Киеве" yields two separate
# facts instead of one fact whose value swallows the rest of the sentence.
_RU_BOUNDARY = r"(.+?)(?=[.,!?]|\s+(?:и|а|но)\b|$)"
_UK_BOUNDARY = r"(.+?)(?=[.,!?]|\s+(?:і|та|а|але)\b|$)"
_EN_BOUNDARY = r"(.+?)(?=[.,!?]|\s+and\b|$)"

_NAME_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"меня зовут\s+" + _RU_BOUNDARY, re.IGNORECASE),
    "uk": re.compile(r"мене звати\s+" + _UK_BOUNDARY, re.IGNORECASE),
    "en": re.compile(r"\bmy name is\s+" + _EN_BOUNDARY, re.IGNORECASE),
}

_LOCATION_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"я жив[уё]\s+в\s+" + _RU_BOUNDARY, re.IGNORECASE),
    "uk": re.compile(r"я живу\s+в\s+" + _UK_BOUNDARY, re.IGNORECASE),
    "en": re.compile(r"\bi live in\s+" + _EN_BOUNDARY, re.IGNORECASE),
}

_LIKES_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"я люблю\s+" + _RU_BOUNDARY, re.IGNORECASE),
    "uk": re.compile(r"я люблю\s+" + _UK_BOUNDARY, re.IGNORECASE),
    "en": re.compile(r"\bi like\s+" + _EN_BOUNDARY, re.IGNORECASE),
}

_WORK_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"я работаю\s+" + _RU_BOUNDARY, re.IGNORECASE),
    "uk": re.compile(r"я працюю\s+" + _UK_BOUNDARY, re.IGNORECASE),
    "en": re.compile(r"\bi work\s+" + _EN_BOUNDARY, re.IGNORECASE),
}

_PATTERNS: tuple[tuple[str, dict[str, re.Pattern[str]]], ...] = (
    ("name", _NAME_PATTERNS),
    ("location", _LOCATION_PATTERNS),
    ("likes", _LIKES_PATTERNS),
    ("work", _WORK_PATTERNS),
)


def extract_facts(text: str, language: str) -> list[ExtractedFact]:
    facts: list[ExtractedFact] = []
    for key, patterns in _PATTERNS:
        pattern = patterns.get(language)
        if pattern is None:
            continue
        match = pattern.search(text)
        if not match:
            continue
        value = match.group(1).strip(" .,!?…")
        if value:
            facts.append(ExtractedFact(key=key, value=value))
    return facts
