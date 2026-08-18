from __future__ import annotations

from datetime import datetime, timedelta

from core.logger import get_logger
from core.message_bus import MessageBus
from modules.calendar.domain import CalendarEvent, RecurrenceRule
from modules.calendar.events import ReminderDue
from modules.calendar.uow import CalendarUnitOfWork

logger = get_logger(__name__)


def create_event(
    uow: CalendarUnitOfWork,
    title: str,
    event_time: datetime,
    remind_before_minutes: int = 0,
    color: str | None = None,
    category: str | None = None,
    recurrence: RecurrenceRule = RecurrenceRule.NONE,
) -> int:
    with uow:
        event_id = uow.events.add(
            CalendarEvent(
                title=title,
                event_time=event_time,
                remind_before_minutes=remind_before_minutes,
                color=color,
                category=category,
                recurrence=recurrence,
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
            if event.recurrence == RecurrenceRule.NONE:
                uow.events.mark_notified(event.id)
            else:
                # Advance in place to the next occurrence strictly after
                # this one (and at/after `now`, so if the reminder checker
                # was down for a while, this catches up to the next real
                # occurrence instead of leaving a backlog of overdue
                # reminders) — a daily/weekly/monthly/yearly reminder keeps
                # firing on every cycle instead of going silent for good
                # after its first ever notification.
                # +1s so the occurrence that just fired (event.event_time
                # itself, still un-advanced at this point) is excluded —
                # next_occurrence_on_or_after treats its argument as
                # inclusive, and without this the very next poll a moment
                # later would find the "same" occurrence due all over again.
                reference = max(now, event.event_time) + timedelta(seconds=1)
                next_occurrence = event.next_occurrence_on_or_after(reference)
                uow.events.reschedule_recurrence(event.id, next_occurrence)
        uow.commit()

    for event in due:
        assert event.id is not None
        await bus.publish(ReminderDue(event_id=event.id, title=event.title, event_time=event.event_time))

    return len(due)
