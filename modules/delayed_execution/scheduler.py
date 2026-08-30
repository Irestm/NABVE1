from __future__ import annotations

import asyncio
import threading
from typing import Callable

from core.dispatcher import CommandDispatcher
from core.logger import get_logger
from modules.delayed_execution import service_layer
from modules.delayed_execution.uow import DelayedExecutionUnitOfWork

logger = get_logger(__name__)


class DelayedCommandRunner:
    """Background poller — every `interval_seconds`, asks the service layer
    to fire any delayed command whose time has come. Same thread/scheduling-
    only shape as modules/calendar/notifier.py's ReminderChecker; the actual
    dispatch lives in service_layer.run_due."""

    def __init__(
        self,
        dispatcher: CommandDispatcher,
        interval_seconds: int = 5,
        uow_factory: Callable[[], DelayedExecutionUnitOfWork] = DelayedExecutionUnitOfWork,
    ) -> None:
        self._dispatcher = dispatcher
        self._interval_seconds = interval_seconds
        self._uow_factory = uow_factory
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="delayed-command-runner")
        self._thread.start()
        logger.info("Delayed command runner started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Delayed command runner stopped")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._tick()
            self._stop_event.wait(self._interval_seconds)

    def _tick(self) -> None:
        try:
            handled = asyncio.run(service_layer.run_due(self._uow_factory(), self._dispatcher))
            if handled:
                logger.info("Fired %d delayed command(s)", handled)
        except Exception:
            logger.exception("Delayed command runner tick failed")
