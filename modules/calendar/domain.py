from __future__ import annotations

import calendar as _calendar
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class RecurrenceRule(str, Enum):
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


def _add_months(dt: datetime, months: int) -> datetime:
    # Clamps the day to the target month's actual length (Jan 31 + 1 month
    # -> Feb 28/29, not an out-of-range date error) — used for both MONTHLY
    # (months=1 step) and YEARLY (months=12 step, so Feb 29 -> Feb 28 on a
    # non-leap year falls out of the same clamp for free).
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, _calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


@dataclass
class CalendarEvent:
    title: str
    event_time: datetime
    remind_before_minutes: int = 0
    notified: bool = False
    id: int | None = None
    created_at: datetime | None = None
    # Hex string ("#2ad8ff") chosen from the UI's basic swatches or its
    # color-wheel picker; None means "use the default accent" — see
    # frontend/src/components/PlannerView.tsx's color picker.
    color: str | None = None
    # Free-text grouping label ("Дни рождения", ...) so related events can
    # be filtered/shown together — deliberately not a separate table/FK:
    # a personal calendar's "category" is just a shared label, not an
    # entity with its own lifecycle.
    category: str | None = None
    recurrence: RecurrenceRule = RecurrenceRule.NONE
    # A critical reminder takes over on firing (see
    # core/voice/critical_reminder.py): it pauses any playing media, puts
    # the orb in its attention state, speaks the reminder, and waits for a
    # spoken acknowledgement before restoring everything. A normal reminder
    # (the default) is just the existing spoken/desktop notification.
    critical: bool = False

    def is_due(self, now: datetime) -> bool:
        if self.notified:
            return False
        remind_at = self.event_time - timedelta(minutes=self.remind_before_minutes)
        return now >= remind_at

    def next_occurrence_on_or_after(self, reference: datetime) -> datetime:
        """For a recurring event, projects event_time forward to the next
        occurrence at/after `reference` (same time-of-day, and same day-of-
        month/year where that's meaningful — see _add_months). A
        non-recurring event, or one whose original event_time is already
        at/after `reference`, just returns event_time unchanged: this is
        only ever about finding the next FUTURE occurrence to show/notify
        for, never about rewriting the stored original."""
        if self.recurrence == RecurrenceRule.NONE or self.event_time >= reference:
            return self.event_time

        elapsed = reference - self.event_time
        if self.recurrence == RecurrenceRule.DAILY:
            period = timedelta(days=1)
            periods_elapsed = -(-elapsed // period)  # ceiling division
            return self.event_time + periods_elapsed * period
        if self.recurrence == RecurrenceRule.WEEKLY:
            period = timedelta(days=7)
            periods_elapsed = -(-elapsed // period)
            return self.event_time + periods_elapsed * period
        if self.recurrence == RecurrenceRule.MONTHLY:
            months_elapsed = (reference.year - self.event_time.year) * 12 + (
                reference.month - self.event_time.month
            )
            occurrence = _add_months(self.event_time, months_elapsed)
            if occurrence < reference:
                occurrence = _add_months(self.event_time, months_elapsed + 1)
            return occurrence
        if self.recurrence == RecurrenceRule.YEARLY:
            years_elapsed = reference.year - self.event_time.year
            occurrence = _add_months(self.event_time, years_elapsed * 12)
            if occurrence < reference:
                occurrence = _add_months(self.event_time, (years_elapsed + 1) * 12)
            return occurrence
        return self.event_time
