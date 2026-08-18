from __future__ import annotations

from datetime import datetime

from modules.calendar.domain import CalendarEvent, RecurrenceRule


def test_next_occurrence_returns_event_time_unchanged_when_not_recurring() -> None:
    event = CalendarEvent(title="A", event_time=datetime(2020, 1, 1, 9, 0))

    assert event.next_occurrence_on_or_after(datetime(2030, 1, 1)) == datetime(2020, 1, 1, 9, 0)


def test_next_occurrence_returns_event_time_unchanged_when_still_in_the_future() -> None:
    event = CalendarEvent(title="A", event_time=datetime(2030, 6, 1, 9, 0), recurrence=RecurrenceRule.DAILY)

    assert event.next_occurrence_on_or_after(datetime(2030, 1, 1)) == datetime(2030, 6, 1, 9, 0)


def test_daily_recurrence_steps_forward_one_day_at_a_time() -> None:
    event = CalendarEvent(title="A", event_time=datetime(2030, 1, 1, 9, 0), recurrence=RecurrenceRule.DAILY)

    # Exactly on a boundary — the reference IS a valid occurrence.
    assert event.next_occurrence_on_or_after(datetime(2030, 1, 5, 9, 0)) == datetime(2030, 1, 5, 9, 0)
    # Between two occurrences — rounds up to the next one, same time-of-day.
    assert event.next_occurrence_on_or_after(datetime(2030, 1, 5, 10, 0)) == datetime(2030, 1, 6, 9, 0)


def test_weekly_recurrence_steps_forward_seven_days_at_a_time() -> None:
    event = CalendarEvent(title="A", event_time=datetime(2030, 1, 1, 9, 0), recurrence=RecurrenceRule.WEEKLY)

    assert event.next_occurrence_on_or_after(datetime(2030, 1, 10)) == datetime(2030, 1, 15, 9, 0)


def test_monthly_recurrence_preserves_day_of_month() -> None:
    event = CalendarEvent(title="A", event_time=datetime(2030, 1, 15, 9, 0), recurrence=RecurrenceRule.MONTHLY)

    assert event.next_occurrence_on_or_after(datetime(2030, 3, 1)) == datetime(2030, 3, 15, 9, 0)


def test_monthly_recurrence_clamps_day_overflow_into_shorter_months() -> None:
    # Jan 31 recurring monthly -> Feb has no 31st, clamps to the 28th (2031
    # is not a leap year).
    event = CalendarEvent(title="A", event_time=datetime(2031, 1, 31, 9, 0), recurrence=RecurrenceRule.MONTHLY)

    assert event.next_occurrence_on_or_after(datetime(2031, 2, 1)) == datetime(2031, 2, 28, 9, 0)


def test_yearly_recurrence_preserves_month_and_day() -> None:
    event = CalendarEvent(title="Birthday", event_time=datetime(1990, 7, 4, 12, 0), recurrence=RecurrenceRule.YEARLY)

    assert event.next_occurrence_on_or_after(datetime(2030, 1, 1)) == datetime(2030, 7, 4, 12, 0)


def test_yearly_recurrence_clamps_feb_29_on_a_non_leap_year() -> None:
    event = CalendarEvent(title="A", event_time=datetime(2028, 2, 29, 9, 0), recurrence=RecurrenceRule.YEARLY)

    # 2029 is not a leap year.
    assert event.next_occurrence_on_or_after(datetime(2029, 1, 1)) == datetime(2029, 2, 28, 9, 0)
    # 2032 is a leap year again — the 29th is back.
    assert event.next_occurrence_on_or_after(datetime(2032, 1, 1)) == datetime(2032, 2, 29, 9, 0)


def test_is_due_ignores_recurrence_and_just_checks_the_stored_event_time() -> None:
    event = CalendarEvent(
        title="A", event_time=datetime(2030, 1, 1, 9, 0), recurrence=RecurrenceRule.DAILY, remind_before_minutes=10
    )

    assert event.is_due(datetime(2030, 1, 1, 8, 55)) is True
    assert event.is_due(datetime(2030, 1, 1, 8, 45)) is False
