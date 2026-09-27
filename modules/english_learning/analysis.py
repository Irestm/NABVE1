from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from modules.english_learning.domain import TARGET_LEVELS, AiExpression, SubtitleCue, WordCandidate
from modules.english_learning.expressions import ExpressionScan, LexiconMatcher, scan_expressions
from modules.english_learning.language_filter import LanguageDetector, LanguageReport, classify_cues
from modules.english_learning.lemmatizer import AnalyzedToken, Lemmatizer
from modules.english_learning.word_selection import CefrLevelSource, select_words


@dataclass(frozen=True)
class Analysis:
    candidates: list[WordCandidate]
    languages: LanguageReport
    analyzed: list[list[AnalyzedToken]]
    expressions: ExpressionScan


def _keeps_expression(candidate: WordCandidate, levels: frozenset[str]) -> bool:
    return candidate.cefr is None or candidate.cefr in levels


def analyze_cues(
    cues: Sequence[SubtitleCue],
    lemmatizer: Lemmatizer,
    cefr: CefrLevelSource,
    *,
    detector: LanguageDetector | None = None,
    lexicon: LexiconMatcher | None = None,
    ai_expressions: Sequence[AiExpression] = (),
    target_levels: Iterable[str] = TARGET_LEVELS,
) -> Analysis:
    levels = frozenset(target_levels)
    languages = classify_cues(cues, detector)
    analyzed = list(lemmatizer.analyze(cue.text for cue in cues))
    scan = scan_expressions(
        cues, analyzed, languages=languages.labels, lexicon=lexicon, ai_expressions=ai_expressions
    )
    words = select_words(
        cues,
        None,
        cefr,
        target_levels=levels,
        languages=languages.labels,
        analyzed=analyzed,
        consumed=scan.consumed,
    )
    expressions = [candidate for candidate in scan.candidates if _keeps_expression(candidate, levels)]
    return Analysis(candidates=words + expressions, languages=languages, analyzed=analyzed, expressions=scan)
