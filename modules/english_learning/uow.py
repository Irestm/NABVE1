from __future__ import annotations

from pathlib import Path

from core.config import DATA_DIR
from core.uow import SqliteUnitOfWork
from modules.english_learning.migrations import migrate
from modules.english_learning.repository import (
    CardRepository,
    CefrRepository,
    EpisodeRepository,
    EpisodeWordRepository,
    LearnSessionRepository,
    ReviewRepository,
    SeriesRepository,
)

ENGLISH_DB_PATH: Path = DATA_DIR / "english_learning.db"


class EnglishUnitOfWork(SqliteUnitOfWork):
    series: SeriesRepository
    episodes: EpisodeRepository
    words: EpisodeWordRepository
    cards: CardRepository
    cefr: CefrRepository
    sessions: LearnSessionRepository
    reviews: ReviewRepository

    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__(db_path or ENGLISH_DB_PATH)

    def __enter__(self) -> "EnglishUnitOfWork":
        super().__enter__()
        self.connection.execute("PRAGMA foreign_keys = ON")
        migrate(self.connection)
        self.series = SeriesRepository(self.connection)
        self.episodes = EpisodeRepository(self.connection)
        self.words = EpisodeWordRepository(self.connection)
        self.cards = CardRepository(self.connection)
        self.cefr = CefrRepository(self.connection)
        self.sessions = LearnSessionRepository(self.connection)
        self.reviews = ReviewRepository(self.connection)
        return self
