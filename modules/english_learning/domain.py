from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

CefrLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]
EpisodeSource = Literal["youtube", "opensubtitles", "manual", "ai_guess"]
WordCategory = Literal["core", "extra"]
ReviewMode = Literal["choice", "input"]

CEFR_LEVELS: tuple[CefrLevel, ...] = ("A1", "A2", "B1", "B2", "C1", "C2")
TARGET_LEVELS: frozenset[str] = frozenset({"A2", "B1"})


@dataclass(frozen=True)
class SubtitleCue:
    index: int
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class WordCandidate:
    lemma: str
    pos: str
    cefr: str | None
    category: WordCategory
    count: int
    example: str
    timestamp_ms: int
    surface: str


@dataclass
class Series:
    title: str
    imdb_id: str | None = None
    tmdb_id: int | None = None
    id: int | None = None
    created_at: datetime | None = None


@dataclass
class Episode:
    series_id: int
    season: int
    episode: int
    source: EpisodeSource
    title: str | None = None
    srt_path: str | None = None
    id: int | None = None
    created_at: datetime | None = None

    @property
    def code(self) -> str:
        return f"S{self.season:02d}E{self.episode:02d}"


@dataclass
class EpisodeWord:
    episode_id: int
    lemma: str
    pos: str
    cefr: str | None
    category: WordCategory
    count: int
    example: str
    timestamp_ms: int
    surface: str
    id: int | None = None


@dataclass
class Card:
    episode_id: int
    word: str
    lemma: str
    pos: str
    cefr: str | None
    translations_ru: list[str]
    definition_en: str
    example: str
    timestamp_ms: int
    category: WordCategory
    id: int | None = None


@dataclass
class LearnSession:
    episode_id: int
    settings: dict[str, object] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    mistakes: int = 0
    id: int | None = None


@dataclass
class ReviewEntry:
    card_id: int
    mode: ReviewMode
    correct: bool
    answer: str
    session_id: int | None = None
    ts: datetime | None = None
    id: int | None = None
