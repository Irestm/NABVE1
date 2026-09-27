from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from modules.english_learning.domain import TARGET_LEVELS, Example, SubtitleCue, WordCandidate, WordCategory
from modules.english_learning.language_filter import CueLanguage
from modules.english_learning.lemmatizer import AnalyzedToken, Lemmatizer

CONTENT_POS: frozenset[str] = frozenset({"NOUN", "VERB", "ADJ", "ADV"})
EXTRA_MIN_COUNT = 3
MIN_WORD_LENGTH = 3
EXAMPLE_MAX_WORDS = 15
MIN_EXAMPLE_WORDS = 4
MAX_EXAMPLES = 3


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
    examples: list[Example] = field(default_factory=list)


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


def trim_example(text: str, surface: str) -> str:
    words = text.split()
    if len(words) <= EXAMPLE_MAX_WORDS:
        return text
    position = next((i for i, word in enumerate(words) if surface.lower() in word.lower()), 0)
    start = max(0, min(position - EXAMPLE_MAX_WORDS // 2, len(words) - EXAMPLE_MAX_WORDS))
    return " ".join(words[start : start + EXAMPLE_MAX_WORDS])


def _remember_example(tally: _Tally, cue: SubtitleCue, surface: str) -> None:
    text = trim_example(cue.text, surface)
    if len(tally.examples) >= MAX_EXAMPLES or any(item.text == text for item in tally.examples):
        return
    tally.examples.append(Example(text=text, timestamp_ms=cue.start_ms, cue_index=cue.index))


def select_words(
    cues: Sequence[SubtitleCue],
    lemmatizer: Lemmatizer | None,
    cefr: CefrLevelSource,
    *,
    target_levels: Iterable[str] = TARGET_LEVELS,
    extra_min_count: int = EXTRA_MIN_COUNT,
    languages: Sequence[CueLanguage] | None = None,
    analyzed: Sequence[list[AnalyzedToken]] | None = None,
    consumed: Collection[tuple[int, int]] = frozenset(),
) -> list[WordCandidate]:
    levels = frozenset(target_levels)
    if analyzed is None:
        if lemmatizer is None:
            raise ValueError("Either a lemmatizer or analyzed tokens are required")
        analyzed = list(lemmatizer.analyze(cue.text for cue in cues))
    tallies: dict[tuple[str, str], _Tally] = {}
    for position, (cue, tokens) in enumerate(zip(cues, analyzed)):
        label = languages[position] if languages is not None else "en"
        if label == "foreign":
            continue
        good_example = _is_good_example(cue.text)
        for token_index, token in enumerate(tokens):
            if not _is_candidate(token) or (cue.index, token_index) in consumed:
                continue
            lemma = token.lemma.lower()
            if label == "short" and cefr.level(lemma, token.pos) is None:
                continue
            key = (lemma, token.pos)
            tally = tallies.get(key)
            if tally is None:
                tally = _Tally(lemma, token.pos, 0, token.text, cue.text, cue.start_ms, good_example)
                tallies[key] = tally
            elif good_example and not tally.good_example:
                tally.example = cue.text
                tally.timestamp_ms = cue.start_ms
                tally.surface = token.text
                tally.good_example = True
            tally.count += 1
            _remember_example(tally, cue, token.text)

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
                example=trim_example(tally.example, tally.surface),
                timestamp_ms=tally.timestamp_ms,
                surface=tally.surface,
                examples=tuple(tally.examples),
                cefr_source="list" if level is not None else None,
            )
        )
    candidates.sort(key=lambda item: (item.category != "core", -item.count, item.lemma))
    return candidates
