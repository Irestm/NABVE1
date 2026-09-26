from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from modules.english_learning.domain import TARGET_LEVELS, SubtitleCue, WordCandidate, WordCategory
from modules.english_learning.lemmatizer import AnalyzedToken, Lemmatizer

CONTENT_POS: frozenset[str] = frozenset({"NOUN", "VERB", "ADJ", "ADV"})
EXTRA_MIN_COUNT = 3
MIN_WORD_LENGTH = 3
EXAMPLE_MAX_WORDS = 15
MIN_EXAMPLE_WORDS = 4


class CefrLevelSource(Protocol):
    def level(self, lemma: str, pos: str) -> str | None: ...


@dataclass
class _Tally:
    lemma: str
    pos: str
    count: int
    surface: str
    example: str
    timestamp_ms: int
    good_example: bool


def _is_candidate(token: AnalyzedToken) -> bool:
    return (
        token.is_alpha
        and not token.is_stop
        and not token.like_num
        and not token.is_named_entity
        and token.pos in CONTENT_POS
        and len(token.lemma) >= MIN_WORD_LENGTH
        and "'" not in token.text
    )


def _is_good_example(text: str) -> bool:
    return MIN_EXAMPLE_WORDS <= len(text.split()) <= EXAMPLE_MAX_WORDS


def _trim_example(text: str, surface: str) -> str:
    words = text.split()
    if len(words) <= EXAMPLE_MAX_WORDS:
        return text
    position = next((i for i, word in enumerate(words) if surface.lower() in word.lower()), 0)
    start = max(0, min(position - EXAMPLE_MAX_WORDS // 2, len(words) - EXAMPLE_MAX_WORDS))
    return " ".join(words[start : start + EXAMPLE_MAX_WORDS])


def select_words(
    cues: list[SubtitleCue],
    lemmatizer: Lemmatizer,
    cefr: CefrLevelSource,
    *,
    target_levels: Iterable[str] = TARGET_LEVELS,
    extra_min_count: int = EXTRA_MIN_COUNT,
) -> list[WordCandidate]:
    levels = frozenset(target_levels)
    tallies: dict[tuple[str, str], _Tally] = {}
    for cue, tokens in zip(cues, lemmatizer.analyze(cue.text for cue in cues)):
        good_example = _is_good_example(cue.text)
        for token in tokens:
            if not _is_candidate(token):
                continue
            lemma = token.lemma.lower()
            key = (lemma, token.pos)
            tally = tallies.get(key)
            if tally is None:
                tallies[key] = _Tally(lemma, token.pos, 1, token.text, cue.text, cue.start_ms, good_example)
                continue
            tally.count += 1
            if good_example and not tally.good_example:
                tally.example = cue.text
                tally.timestamp_ms = cue.start_ms
                tally.surface = token.text
                tally.good_example = True

    candidates: list[WordCandidate] = []
    for tally in tallies.values():
        level = cefr.level(tally.lemma, tally.pos)
        category: WordCategory
        if level in levels:
            category = "core"
        elif level is None and tally.count >= extra_min_count:
            category = "extra"
        else:
            continue
        candidates.append(
            WordCandidate(
                lemma=tally.lemma,
                pos=tally.pos,
                cefr=level,
                category=category,
                count=tally.count,
                example=_trim_example(tally.example, tally.surface),
                timestamp_ms=tally.timestamp_ms,
                surface=tally.surface,
            )
        )
    candidates.sort(key=lambda item: (item.category != "core", -item.count, item.lemma))
    return candidates
