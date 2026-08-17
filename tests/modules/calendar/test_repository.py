from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from modules.calendar.domain import CalendarEvent
from modules.calendar.repository import CalendarEventRepository


def _connect(tmp_db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def test_add_assigns_an_autoincrement_id(tmp_db_path: Path) -> None:
    conn = _connect(tmp_db_path)
    repo = CalendarEventRepository(conn)

    first = repo.add(CalendarEvent(title="A", event_time=datetime(2030, 1, 1)))
    second = repo.add(CalendarEvent(title="B", event_time=datetime(2030, 1, 2)))

    assert second == first + 1


def test_get_returns_none_for_unknown_id(tmp_db_path: Path) -> None:
    conn = _connect(tmp_db_path)
    repo = CalendarEventRepository(conn)

    assert repo.get(999) is None


def test_list_upcoming_is_ordered_by_event_time_and_excludes_the_past(tmp_db_path: Path) -> None:
    conn = _connect(tmp_db_path)
    repo = CalendarEventRepository(conn)
    now = datetime(2030, 1, 1, 12, 0)
    later_id = repo.add(CalendarEvent(title="Later", event_time=now + timedelta(days=2)))
    sooner_id = repo.add(CalendarEvent(title="Sooner", event_time=now + timedelta(hours=1)))
    repo.add(CalendarEvent(title="Past", event_time=now - timedelta(days=1)))

    upcoming = repo.list_upcoming(now)

    assert [e.id for e in upcoming] == [sooner_id, later_id]


def test_list_upcoming_respects_limit(tmp_db_path: Path) -> None:
    conn = _connect(tmp_db_path)
    repo = CalendarEventRepository(conn)
    now = datetime(2030, 1, 1)
    for i in range(5):
        repo.add(CalendarEvent(title=f"E{i}", event_time=now + timedelta(hours=i)))

    upcoming = repo.list_upcoming(now, limit=2)

    assert len(upcoming) == 2


def test_delete_returns_true_then_false(tmp_db_path: Path) -> None:
    conn = _connect(tmp_db_path)
    repo = CalendarEventRepository(conn)
    event_id = repo.add(CalendarEvent(title="A", event_time=datetime(2030, 1, 1)))

    assert repo.delete(event_id) is True
    assert repo.delete(event_id) is False
    assert repo.get(event_id) is None


def test_mark_notified_flips_the_flag(tmp_db_path: Path) -> None:
    conn = _connect(tmp_db_path)
    repo = CalendarEventRepository(conn)
    event_id = repo.add(CalendarEvent(title="A", event_time=datetime(2030, 1, 1)))

    repo.mark_notified(event_id)

    stored = repo.get(event_id)
    assert stored is not None and stored.notified is True


def test_list_not_notified_excludes_notified_events(tmp_db_path: Path) -> None:
    conn = _connect(tmp_db_path)
    repo = CalendarEventRepository(conn)
    pending_id = repo.add(CalendarEvent(title="Pending", event_time=datetime(2030, 1, 1)))
    repo.add(CalendarEvent(title="Done", event_time=datetime(2030, 1, 1), notified=True))

    result = repo.list_not_notified()

    assert [e.id for e in result] == [pending_id]
