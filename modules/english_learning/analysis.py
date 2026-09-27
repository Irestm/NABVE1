from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from modules.english_learning.domain import SubtitleCue, WordCandidate
from modules.english_learning.language_filter import LanguageDetector, LanguageReport, classify_cues
from modules.english_learning.lemmatizer import AnalyzedToken, Lemmatizer
from modules.english_learning.word_selection import CefrLevelSource, select_words


@dataclass(frozen=True)
class Analysis:
    candidates: list[WordCandidate]
    languages: LanguageReport
    analyzed: list[list[AnalyzedToken]]


def analyze_cues(
    cues: Sequence[SubtitleCue],
    lemmatizer: Lemmatizer,
    cefr: CefrLevelSource,
    *,
    detector: LanguageDetector | None = None,
) -> Analysis:
    languages = classify_cues(cues, detector)
    analyzed = list(lemmatizer.analyze(cue.text for cue in cues))
    candidates = select_words(cues, None, cefr, languages=languages.labels, analyzed=analyzed)
    return Analysis(candidates=candidates, languages=languages, analyzed=analyzed)
