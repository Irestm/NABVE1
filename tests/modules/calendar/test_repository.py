from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from modules.calendar.domain import CalendarEvent, RecurrenceRule
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


def test_list_upcoming_includes_a_recurring_event_whose_own_event_time_is_in_the_past(
    tmp_db_path: Path,
) -> None:
    conn = _connect(tmp_db_path)
    repo = CalendarEventRepository(conn)
    now = datetime(2030, 6, 15, 12, 0)
    recurring_id = repo.add(
        CalendarEvent(title="Birthday", event_time=datetime(1990, 7, 4, 9, 0), recurrence=RecurrenceRule.YEARLY)
    )
    repo.add(CalendarEvent(title="Old one-off", event_time=datetime(2020, 1, 1)))  # correctly excluded

    upcoming = repo.list_upcoming(now)

    assert [e.id for e in upcoming] == [recurring_id]


def test_list_upcoming_sorts_a_recurring_event_by_its_projected_next_occurrence(tmp_db_path: Path) -> None:
    conn = _connect(tmp_db_path)
    repo = CalendarEventRepository(conn)
    now = datetime(2030, 1, 1)
    # Recurs daily from long ago -> its next occurrence is effectively
    # "today", sooner than the one-off event three days out.
    daily_id = repo.add(
        CalendarEvent(title="Daily", event_time=datetime(2020, 1, 1, 9, 0), recurrence=RecurrenceRule.DAILY)
    )
    later_id = repo.add(CalendarEvent(title="Later", event_time=now + timedelta(days=3)))

    upcoming = repo.list_upcoming(now)

    assert [e.id for e in upcoming] == [daily_id, later_id]


def test_reschedule_recurrence_updates_event_time_and_clears_notified(tmp_db_path: Path) -> None:
    conn = _connect(tmp_db_path)
    repo = CalendarEventRepository(conn)
    event_id = repo.add(
        CalendarEvent(title="A", event_time=datetime(2030, 1, 1, 9, 0), recurrence=RecurrenceRule.DAILY)
    )
    repo.mark_notified(event_id)

    repo.reschedule_recurrence(event_id, datetime(2030, 1, 2, 9, 0))

    stored = repo.get(event_id)
    assert stored is not None
    assert stored.event_time == datetime(2030, 1, 2, 9, 0)
    assert stored.notified is False


def test_add_persists_color_category_and_recurrence(tmp_db_path: Path) -> None:
    conn = _connect(tmp_db_path)
    repo = CalendarEventRepository(conn)
    event_id = repo.add(
        CalendarEvent(
            title="A",
            event_time=datetime(2030, 1, 1),
            color="#2ad8ff",
            category="Дни рождения",
            recurrence=RecurrenceRule.YEARLY,
        )
    )

    stored = repo.get(event_id)

    assert stored is not None
    assert stored.color == "#2ad8ff"
    assert stored.category == "Дни рождения"
    assert stored.recurrence == RecurrenceRule.YEARLY


def test_list_not_notified_excludes_notified_events(tmp_db_path: Path) -> None:
    conn = _connect(tmp_db_path)
    repo = CalendarEventRepository(conn)
    pending_id = repo.add(CalendarEvent(title="Pending", event_time=datetime(2030, 1, 1)))
    repo.add(CalendarEvent(title="Done", event_time=datetime(2030, 1, 1), notified=True))

    result = repo.list_not_notified()

    assert [e.id for e in result] == [pending_id]
