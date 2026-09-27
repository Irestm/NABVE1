from __future__ import annotations

from pathlib import Path

from core.config import DATA_DIR
from core.uow import SqliteUnitOfWork
from modules.english_learning.migrations import migrate
from modules.english_learning.repository import (
    AiExpressionRepository,
    AssistantRepository,
    CardRepository,
    CefrRepository,
    EpisodeRepository,
    EpisodeStatsRepository,
    EpisodeWordRepository,
    FilterSettingsRepository,
    KeyValueRepository,
    LearnSessionRepository,
    ListeningRepository,
    MweLexiconRepository,
    ReviewRepository,
    TitleRepository,
)

ENGLISH_DB_PATH: Path = DATA_DIR / "english_learning.db"


class EnglishUnitOfWork(SqliteUnitOfWork):
    titles: TitleRepository
    episodes: EpisodeRepository
    words: EpisodeWordRepository
    cards: CardRepository
    cefr: CefrRepository
    lexicon: MweLexiconRepository
    ai_expressions: AiExpressionRepository
    stats: EpisodeStatsRepository
    filters: FilterSettingsRepository
    settings: KeyValueRepository
    ui_settings: KeyValueRepository
    sessions: LearnSessionRepository
    reviews: ReviewRepository
    listening: ListeningRepository
    assistant: AssistantRepository

    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__(db_path or ENGLISH_DB_PATH)

    def __enter__(self) -> "EnglishUnitOfWork":
        super().__enter__()
        self.connection.execute("PRAGMA foreign_keys = ON")
        migrate(self.connection)
        self.titles = TitleRepository(self.connection)
        self.episodes = EpisodeRepository(self.connection)
        self.words = EpisodeWordRepository(self.connection)
        self.cards = CardRepository(self.connection)
        self.cefr = CefrRepository(self.connection)
        self.lexicon = MweLexiconRepository(self.connection)
        self.ai_expressions = AiExpressionRepository(self.connection)
        self.stats = EpisodeStatsRepository(self.connection)
        self.filters = FilterSettingsRepository(self.connection)
        self.settings = KeyValueRepository(self.connection, "english_settings")
        self.ui_settings = KeyValueRepository(self.connection, "ui_settings")
        self.sessions = LearnSessionRepository(self.connection)
        self.reviews = ReviewRepository(self.connection)
        self.listening = ListeningRepository(self.connection)
        self.assistant = AssistantRepository(self.connection)
        return self
