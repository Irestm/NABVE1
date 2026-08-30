from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from core.message_bus import MessageBus
from modules.calendar import service_layer
from modules.calendar.domain import CalendarEvent, RecurrenceRule
from modules.calendar.events import ReminderDue
from modules.calendar.uow import CalendarUnitOfWork


class FakeCalendarEventRepository:
    def __init__(self) -> None:
        self._events: dict[int, CalendarEvent] = {}
        self._next_id = 1

    def add(self, item: CalendarEvent) -> int:
        item.id = self._next_id
        self._events[self._next_id] = item
        self._next_id += 1
        return item.id

    def get(self, key: int) -> CalendarEvent | None:
        return self._events.get(key)

    def list_upcoming(self, now: datetime, limit: int = 20) -> list[CalendarEvent]:
        upcoming = sorted(
            (e for e in self._events.values() if e.event_time >= now),
            key=lambda e: e.event_time,
        )
        return upcoming[:limit]

    def list_not_notified(self) -> list[CalendarEvent]:
        return [e for e in self._events.values() if not e.notified]

    def delete(self, key: int) -> bool:
        return self._events.pop(key, None) is not None

    def mark_notified(self, key: int) -> None:
        self._events[key].notified = True

    def reschedule_recurrence(self, key: int, next_event_time: datetime) -> None:
        self._events[key].event_time = next_event_time
        self._events[key].notified = False


class FakeCalendarUnitOfWork:
    def __init__(self) -> None:
        self.events = FakeCalendarEventRepository()

    def __enter__(self) -> "FakeCalendarUnitOfWork":
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


def test_create_and_list_upcoming() -> None:
    uow = FakeCalendarUnitOfWork()
    event_id = service_layer.create_event(uow, "Meeting", datetime.now() + timedelta(hours=1))
    events = service_layer.list_upcoming(uow)
    assert [e.id for e in events] == [event_id]


def test_delete_event() -> None:
    uow = FakeCalendarUnitOfWork()
    event_id = service_layer.create_event(uow, "Meeting", datetime.now() + timedelta(hours=1))
    assert service_layer.delete_event(uow, event_id) is True
    assert service_layer.delete_event(uow, event_id) is False


async def test_check_due_reminders_publishes_one_event_per_due_reminder() -> None:
    uow = FakeCalendarUnitOfWork()
    now = datetime.now()
    due_id = service_layer.create_event(uow, "Due now", now - timedelta(minutes=1))
    service_layer.create_event(uow, "Not due yet", now + timedelta(days=1))

    bus = MessageBus()
    received: list[ReminderDue] = []

    async def handler(event: ReminderDue) -> None:
        received.append(event)

    bus.subscribe(ReminderDue, handler)

    handled = await service_layer.check_due_reminders(uow, bus, now=now)

    assert handled == 1
    assert [e.event_id for e in received] == [due_id]
    # Marked notified so the next poll doesn't re-fire it.
    assert uow.events.get(due_id).notified is True


async def test_check_due_reminders_advances_a_recurring_event_instead_of_marking_it_done_forever() -> None:
    uow = FakeCalendarUnitOfWork()
    now = datetime(2030, 1, 5, 9, 0)
    event_id = service_layer.create_event(
        uow, "Daily standup", datetime(2030, 1, 1, 9, 0), recurrence=RecurrenceRule.DAILY
    )

    bus = MessageBus()
    received: list[ReminderDue] = []

    async def handler(event: ReminderDue) -> None:
        received.append(event)

    bus.subscribe(ReminderDue, handler)

    handled = await service_layer.check_due_reminders(uow, bus, now=now)

    assert handled == 1
    stored = uow.events.get(event_id)
    assert stored is not None
    # Still not "notified forever" — advanced to the next daily occurrence,
    # ready to fire again tomorrow.
    assert stored.notified is False
    assert stored.event_time == datetime(2030, 1, 6, 9, 0)


def test_domain_is_due_respects_remind_before_minutes() -> None:
    event = CalendarEvent(
        title="x", event_time=datetime(2030, 1, 1, 12, 0), remind_before_minutes=30
    )
    assert event.is_due(datetime(2030, 1, 1, 11, 29)) is False
    assert event.is_due(datetime(2030, 1, 1, 11, 30)) is True
    assert event.is_due(datetime(2030, 1, 1, 12, 30)) is True


def test_domain_is_due_false_once_notified() -> None:
    event = CalendarEvent(
        title="x", event_time=datetime(2030, 1, 1, 12, 0), notified=True
    )
    assert event.is_due(datetime(2030, 1, 1, 13, 0)) is False


async def test_real_sqlite_repository_reminder_flow(tmp_db_path: Path) -> None:
    """Integration test against the real repository/uow (sqlite), not the fake."""
    uow_factory = lambda: CalendarUnitOfWork(db_path=tmp_db_path)
    now = datetime.now()
    event_id = service_layer.create_event(uow_factory(), "Due", now - timedelta(minutes=1))

    bus = MessageBus()
    received: list[ReminderDue] = []

    async def handler(event: ReminderDue) -> None:
        received.append(event)

    bus.subscribe(ReminderDue, handler)
    handled = await service_layer.check_due_reminders(uow_factory(), bus, now=now)

    assert handled == 1
    assert received[0].event_id == event_id


async def test_check_due_reminders_propagates_the_critical_flag() -> None:
    uow = FakeCalendarUnitOfWork()
    now = datetime.now()
    service_layer.create_event(uow, "Normal", now - timedelta(minutes=1))
    service_layer.create_event(uow, "Critical", now - timedelta(minutes=1), critical=True)

    bus = MessageBus()
    received: list[ReminderDue] = []

    async def handler(event: ReminderDue) -> None:
        received.append(event)

    bus.subscribe(ReminderDue, handler)
    await service_layer.check_due_reminders(uow, bus, now=now)

    by_title = {e.title: e.critical for e in received}
    assert by_title == {"Normal": False, "Critical": True}
