from __future__ import annotations

from datetime import datetime

from core.logger import get_logger
from core.message_bus import MessageBus
from modules.calendar.domain import CalendarEvent
from modules.calendar.events import ReminderDue
from modules.calendar.uow import CalendarUnitOfWork

logger = get_logger(__name__)


def create_event(
    uow: CalendarUnitOfWork, title: str, event_time: datetime, remind_before_minutes: int = 0
) -> int:
    with uow:
        event_id = uow.events.add(
            CalendarEvent(
                title=title, event_time=event_time, remind_before_minutes=remind_before_minutes
            )
        )
        uow.commit()
    return event_id


def list_upcoming(uow: CalendarUnitOfWork, limit: int = 20) -> list[CalendarEvent]:
    with uow:
        return uow.events.list_upcoming(datetime.now(), limit)


def delete_event(uow: CalendarUnitOfWork, event_id: int) -> bool:
    with uow:
        deleted = uow.events.delete(event_id)
        uow.commit()
    return deleted


async def check_due_reminders(uow: CalendarUnitOfWork, bus: MessageBus, now: datetime | None = None) -> int:
    """Finds events whose reminder window has arrived, publishes one
    ReminderDue per event (subscribers decide how to actually notify — see
    modules/calendar/notification_adapter.py and
    core/voice/announcements.py), and marks them notified. Returns the
    count handled, so callers (ReminderChecker's poll loop) can log
    something useful without caring about the events themselves."""
    now = now or datetime.now()
    with uow:
        due = [event for event in uow.events.list_not_notified() if event.is_due(now)]
        for event in due:
            assert event.id is not None
            uow.events.mark_notified(event.id)
        uow.commit()

    for event in due:
        assert event.id is not None
        await bus.publish(ReminderDue(event_id=event.id, title=event.title, event_time=event.event_time))

    return len(due)
