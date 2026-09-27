from __future__ import annotations

import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from core.logger import get_logger
from modules.english_learning.domain import SubtitleCue

logger = get_logger(__name__)

MIN_WORDS_FOR_LANGUAGE = 3
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")
_LINGUA_LANGUAGES: tuple[str, ...] = (
    "ENGLISH",
    "SPANISH",
    "FRENCH",
    "GERMAN",
    "ITALIAN",
    "PORTUGUESE",
    "RUSSIAN",
    "UKRAINIAN",
    "CHINESE",
    "JAPANESE",
    "KOREAN",
    "ARABIC",
)

CueLanguage = Literal["en", "foreign", "short"]


class LanguageDetector(Protocol):
    def is_english(self, text: str) -> bool: ...


class AlwaysEnglish:
    def is_english(self, text: str) -> bool:
        return True


class LinguaDetector:
    def __init__(self) -> None:
        self._detector: Any = None
        self._english: Any = None
        self._lock = threading.Lock()
        self._unavailable = False

    def _build(self) -> Any:
        with self._lock:
            if self._detector is None and not self._unavailable:
                try:
                    from lingua import Language, LanguageDetectorBuilder
                except ImportError:
                    logger.warning("lingua-language-detector is not installed; non-English lines are not filtered")
                    self._unavailable = True
                    return None
                languages = [getattr(Language, name) for name in _LINGUA_LANGUAGES]
                self._detector = LanguageDetectorBuilder.from_languages(*languages).build()
                self._english = Language.ENGLISH
            return self._detector

    def is_english(self, text: str) -> bool:
        detector = self._build()
        if detector is None:
            return True
        detected = detector.detect_language_of(text)
        return detected is None or detected == self._english


_shared: LinguaDetector | None = None


def get_detector() -> LinguaDetector:
    global _shared
    if _shared is None:
        _shared = LinguaDetector()
    return _shared


def word_count(text: str) -> int:
    return len(_WORD.findall(text))


def classify(text: str, detector: LanguageDetector) -> CueLanguage:
    if word_count(text) < MIN_WORDS_FOR_LANGUAGE:
        return "short"
    return "en" if detector.is_english(text) else "foreign"


@dataclass(frozen=True)
class LanguageReport:
    labels: list[CueLanguage]

    @property
    def foreign_count(self) -> int:
        return sum(1 for label in self.labels if label == "foreign")

    @property
    def foreign_share(self) -> float:
        return self.foreign_count / len(self.labels) if self.labels else 0.0


def classify_cues(cues: Sequence[SubtitleCue], detector: LanguageDetector | None = None) -> LanguageReport:
    active = detector or get_detector()
    return LanguageReport(labels=[classify(cue.text, active) for cue in cues])
