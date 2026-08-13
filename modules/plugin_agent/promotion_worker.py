from __future__ import annotations

import asyncio
import threading
from typing import Callable

from core.logger import get_logger
from modules.plugin_agent import service_layer
from modules.plugin_agent.uow import PluginAgentUnitOfWork

logger = get_logger(__name__)


class GapPromotionWorker:
    """Periodically turns 'ready_for_generation' candidates into pending
    plugins by delegating to service_layer.process_next_ready_candidate —
    this class only owns the polling thread."""

    def __init__(
        self,
        interval_seconds: int = 300,
        uow_factory: Callable[[], PluginAgentUnitOfWork] = PluginAgentUnitOfWork,
    ) -> None:
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
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="plugin-gap-promotion"
        )
        self._thread.start()
        logger.info("Plugin gap promotion worker started (interval=%ss)", self._interval_seconds)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Plugin gap promotion worker stopped")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                asyncio.run(service_layer.process_next_ready_candidate(self._uow_factory()))
            except Exception:
                logger.exception("Gap promotion worker tick failed")
            self._stop_event.wait(self._interval_seconds)
