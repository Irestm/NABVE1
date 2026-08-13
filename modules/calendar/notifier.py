from __future__ import annotations

import asyncio
import threading
from typing import Callable

from core.logger import get_logger
from core.message_bus import MessageBus, message_bus
from modules.calendar import service_layer
from modules.calendar.uow import CalendarUnitOfWork

logger = get_logger(__name__)


class ReminderChecker:
    """Background poller: every `interval_seconds`, asks the calendar
    service layer which reminders are due and lets it publish ReminderDue
    to the message bus. This class only owns the thread/scheduling — actual
    notification delivery lives in subscribers (desktop notification,
    optionally spoken reminder), so this file no longer needs to know how a
    reminder is presented to the user."""

    def __init__(
        self,
        interval_seconds: int = 30,
        uow_factory: Callable[[], CalendarUnitOfWork] = CalendarUnitOfWork,
        bus: MessageBus = message_bus,
    ) -> None:
        self._interval_seconds = interval_seconds
        self._uow_factory = uow_factory
        self._bus = bus
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="calendar-reminder-checker"
        )
        self._thread.start()
        logger.info("Reminder checker started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Reminder checker stopped")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._check_once()
            self._stop_event.wait(self._interval_seconds)

    def _check_once(self) -> None:
        try:
            handled = asyncio.run(
                service_layer.check_due_reminders(self._uow_factory(), self._bus)
            )
            if handled:
                logger.info("Handled %d due reminder(s)", handled)
        except Exception:
            logger.exception("Failed while checking due reminders")
