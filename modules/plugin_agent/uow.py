from __future__ import annotations

from pathlib import Path

from core.config import settings
from core.uow import SqliteUnitOfWork
from modules.plugin_agent.repository import GapCandidateRepository


class PluginAgentUnitOfWork(SqliteUnitOfWork):
    candidates: GapCandidateRepository

    def __init__(self, db_path: Path = settings.db_path) -> None:
        super().__init__(db_path)

    def __enter__(self) -> "PluginAgentUnitOfWork":
        super().__enter__()
        self.candidates = GapCandidateRepository(self.connection)
        return self
