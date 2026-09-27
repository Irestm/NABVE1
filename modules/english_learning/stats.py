from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING

from modules.english_learning.domain import ABOVE_STORED_LEVELS, CEFR_LEVELS, EpisodeStats, SubtitleCue
from modules.english_learning.language_filter import CueLanguage
from modules.english_learning.lemmatizer import AnalyzedToken
from modules.english_learning.word_selection import CefrLevelSource

if TYPE_CHECKING:
    from modules.english_learning.expressions import ExpressionHit

UNLEVELED = "none"
TOP_ABOVE_B2 = 15
_FILLER_POS = frozenset({"INTJ", "PROPN", "X", "SYM", "PUNCT", "NUM", "SPACE"})


def counts_toward_vocabulary(token: AnalyzedToken) -> bool:
    return token.is_alpha and not token.is_named_entity and not token.like_num and token.pos not in _FILLER_POS


def compute_stats(
    cues: Sequence[SubtitleCue],
    analyzed: Sequence[Sequence[AnalyzedToken]],
    languages: Sequence[CueLanguage],
    cefr: CefrLevelSource,
    hits: Sequence["ExpressionHit"] = (),
) -> EpisodeStats:
    tokens_by_level: Counter[str] = Counter()
    lemma_counts: Counter[str] = Counter()
    lemma_levels: dict[str, str | None] = {}
    spoken_words = 0
    speech_ms = 0
    for cue, tokens, label in zip(cues, analyzed, languages):
        if label == "foreign":
            continue
        speech_ms += max(0, cue.end_ms - cue.start_ms)
        for token in tokens:
            if token.is_alpha:
                spoken_words += 1
            if not counts_toward_vocabulary(token):
                continue
            lemma = token.lemma.lower()
            level = lemma_levels[lemma] if lemma in lemma_levels else cefr.level(lemma, token.pos)
            lemma_levels[lemma] = level
            lemma_counts[lemma] += 1
            tokens_by_level[level or UNLEVELED] += 1

    token_count = sum(tokens_by_level.values())
    lemmas_by_level: Counter[str] = Counter(level or UNLEVELED for level in lemma_levels.values())
    idioms = sum(1 for hit in hits if hit.kind == "idiom")
    slang = sum(1 for hit in hits if hit.kind == "slang")
    minutes = speech_ms / 60_000
    foreign = sum(1 for label in languages if label == "foreign")
    top = [
        (lemma, count)
        for lemma, count in lemma_counts.most_common()
        if lemma_levels.get(lemma) in ABOVE_STORED_LEVELS
    ][:TOP_ABOVE_B2]
    return EpisodeStats(
        token_count=token_count,
        lemma_count=len(lemma_counts),
        tokens_by_level={level: tokens_by_level.get(level, 0) for level in (*CEFR_LEVELS, UNLEVELED)},
        lemmas_by_level={level: lemmas_by_level.get(level, 0) for level in (*CEFR_LEVELS, UNLEVELED)},
        expressions_per_1000=round((idioms + slang) / token_count * 1000, 2) if token_count else 0.0,
        words_per_minute=round(spoken_words / minutes, 1) if minutes > 0 else 0.0,
        non_english_share=round(foreign / len(languages), 4) if languages else 0.0,
        off_list_share=round(tokens_by_level.get(UNLEVELED, 0) / token_count, 4) if token_count else 0.0,
        top_above_b2=top,
        lemma_counts=dict(lemma_counts),
        lemma_levels=lemma_levels,
        cue_count=len(cues),
        non_english_cues=foreign,
        speech_minutes=round(minutes, 2),
        slang_count=slang,
        idiom_count=idioms,
    )
