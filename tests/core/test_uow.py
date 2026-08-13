from __future__ import annotations

import sqlite3
from pathlib import Path

from core.uow import SqliteUnitOfWork


def _make_table(uow: SqliteUnitOfWork) -> None:
    uow.connection.execute("CREATE TABLE IF NOT EXISTS t (value TEXT)")


def test_commit_persists_across_separate_units_of_work(tmp_db_path: Path) -> None:
    with SqliteUnitOfWork(tmp_db_path) as uow:
        _make_table(uow)
        uow.connection.execute("INSERT INTO t VALUES ('a')")
        uow.commit()

    with SqliteUnitOfWork(tmp_db_path) as uow:
        rows = uow.connection.execute("SELECT value FROM t").fetchall()
    assert [r[0] for r in rows] == ["a"]


def test_uncommitted_changes_are_rolled_back_on_exit(tmp_db_path: Path) -> None:
    with SqliteUnitOfWork(tmp_db_path) as uow:
        _make_table(uow)
        uow.commit()

    with SqliteUnitOfWork(tmp_db_path) as uow:
        uow.connection.execute("INSERT INTO t VALUES ('b')")
        # No uow.commit() here — should be rolled back on __exit__.

    with SqliteUnitOfWork(tmp_db_path) as uow:
        rows = uow.connection.execute("SELECT value FROM t").fetchall()
    assert rows == []


def test_exception_inside_the_block_rolls_back(tmp_db_path: Path) -> None:
    with SqliteUnitOfWork(tmp_db_path) as uow:
        _make_table(uow)
        uow.commit()

    try:
        with SqliteUnitOfWork(tmp_db_path) as uow:
            uow.connection.execute("INSERT INTO t VALUES ('c')")
            raise ValueError("boom")
    except ValueError:
        pass

    with SqliteUnitOfWork(tmp_db_path) as uow:
        rows = uow.connection.execute("SELECT value FROM t").fetchall()
    assert rows == []
