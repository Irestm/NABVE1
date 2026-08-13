from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from types import TracebackType


class AbstractUnitOfWork(ABC):
    """A unit of work groups the repository access(es) needed for one use
    case into a single transaction boundary, so service-layer functions
    never talk to sqlite (or any other storage) directly. See
    https://www.cosmicpython.com/book/chapter_06_uow.html."""

    def __enter__(self) -> "AbstractUnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # Uncommitted-on-exit means "the service layer forgot to call
        # commit()" or "an exception was raised" — either way, roll back
        # rather than silently persisting a half-finished use case.
        self.rollback()

    @abstractmethod
    def commit(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def rollback(self) -> None:
        raise NotImplementedError


class SqliteUnitOfWork(AbstractUnitOfWork):
    """Opens one short-lived sqlite3.Connection per `with` block — the same
    connect-per-call lifecycle every module already used before this
    refactor, just centralized so each module's UoW subclass only has to
    attach its own repository/repositories in `__enter__`."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self.connection: sqlite3.Connection

    def __enter__(self) -> "SqliteUnitOfWork":
        self.connection = sqlite3.connect(self._db_path)
        self.connection.row_factory = sqlite3.Row
        return super().__enter__()  # type: ignore[return-value]

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        super().__exit__(exc_type, exc, traceback)
        self.connection.close()

    def commit(self) -> None:
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()
