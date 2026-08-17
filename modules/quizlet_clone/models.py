from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class SetSource(str, Enum):
    QUIZLET_IMPORT = "quizlet_import"
    MANUAL = "manual"


class GameMode(str, Enum):
    FLASHCARDS = "flashcards"
    LEARN = "learn"
    MATCH = "match"
    TEST = "test"
    VOICE = "voice"


@dataclass
class Term:
    id: str
    set_id: str
    term: str
    definition: str
    position: int
    times_seen: int = 0
    times_correct: int = 0
    times_wrong: int = 0

    @property
    def learned(self) -> bool:
        # A term counts as "learned" once it's been answered correctly at
        # least twice in a row more than it's been missed — a simple,
        # non-spaced-repetition heuristic per the ТЗ's "не переусложнять".
        return self.times_correct >= 2 and self.times_correct > self.times_wrong


@dataclass
class StudySet:
    id: str
    title: str
    source: SetSource
    quizlet_set_id: str | None = None
    created_at: datetime | None = None
    terms: list[Term] = field(default_factory=list)
    attempts_count: int = 0

    @property
    def progress_percent(self) -> int:
        if not self.terms:
            return 0
        learned = sum(1 for term in self.terms if term.learned)
        return round(100 * learned / len(self.terms))


@dataclass
class GameAttempt:
    id: int | None
    set_id: str
    mode: GameMode
    started_at: datetime
    finished_at: datetime | None
    score: int
    total: int


@dataclass
class LibrarySetSummary:
    """One row scraped from the user's Quizlet library listing — see
    quizlet_scraper.list_library_sets. Not persisted on its own; importing
    turns it into a StudySet via service_layer.import_or_refresh_set."""

    quizlet_set_id: str
    title: str
    term_count: int
