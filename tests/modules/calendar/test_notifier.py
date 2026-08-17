from __future__ import annotations

import time
from datetime import datetime, timedelta

from core.message_bus import MessageBus
from modules.calendar import service_layer
from modules.calendar.domain import CalendarEvent
from modules.calendar.events import ReminderDue
from modules.calendar.notifier import ReminderChecker
from modules.calendar.uow import CalendarUnitOfWork


def _uow(tmp_path) -> CalendarUnitOfWork:
    return CalendarUnitOfWork(tmp_path / "assistant.db")


def test_check_once_publishes_reminder_due_and_marks_notified(tmp_path) -> None:
    uow = _uow(tmp_path)
    with uow:
        event_id = uow.events.add(
            CalendarEvent(title="Встреча", event_time=datetime.now() - timedelta(minutes=1))
        )
        uow.commit()

    bus = MessageBus()
    received: list[ReminderDue] = []

    async def _record(event: ReminderDue) -> None:
        received.append(event)

    bus.subscribe(ReminderDue, _record)
    checker = ReminderChecker(uow_factory=lambda: uow, bus=bus)

    checker._check_once()

    assert [e.event_id for e in received] == [event_id]
    with uow:
        stored = uow.events.get(event_id)
    assert stored is not None and stored.notified is True


def test_check_once_does_not_republish_already_notified_events(tmp_path) -> None:
    uow = _uow(tmp_path)
    with uow:
        uow.events.add(CalendarEvent(title="Старое", event_time=datetime.now() - timedelta(days=1), notified=True))
        uow.commit()

    bus = MessageBus()
    received: list[ReminderDue] = []

    async def _record(event: ReminderDue) -> None:
        received.append(event)

    bus.subscribe(ReminderDue, _record)
    checker = ReminderChecker(uow_factory=lambda: uow, bus=bus)

    checker._check_once()

    assert received == []


def test_check_once_swallows_service_layer_exceptions(tmp_path, monkeypatch) -> None:
    checker = ReminderChecker(uow_factory=lambda: _uow(tmp_path))

    async def _boom(_uow, _bus, now=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(service_layer, "check_due_reminders", _boom)

    checker._check_once()  # must not raise


def test_start_and_stop_lifecycle(tmp_path) -> None:
    checker = ReminderChecker(interval_seconds=60, uow_factory=lambda: _uow(tmp_path))
    assert checker.is_running is False

    checker.start()
    try:
        assert checker.is_running is True
        checker.start()  # calling start() again while running is a no-op
    finally:
        checker.stop()

    assert checker.is_running is False


def test_run_loop_ticks_until_stopped(tmp_path) -> None:
    ticks: list[int] = []
    checker = ReminderChecker(interval_seconds=0, uow_factory=lambda: _uow(tmp_path))
    checker._check_once = lambda: ticks.append(1)  # type: ignore[method-assign]

    checker.start()
    time.sleep(0.05)
    checker.stop()

    assert len(ticks) >= 1
