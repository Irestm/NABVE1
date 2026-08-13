from __future__ import annotations

import threading
from typing import Callable

from core.config import settings
from core.logger import get_logger
from modules.meeting_recorder import service_layer
from modules.meeting_recorder.adapters import LocalAudioConverter
from modules.meeting_recorder.ports import AudioConverterPort
from modules.meeting_recorder.uow import MeetingRecordingUnitOfWork

logger = get_logger(__name__)


class RecordingProcessor:
    """Background poller: converts PROCESSING recordings to the final
    Opus/OGG file and independently validates their duration (see
    service_layer.process_next). Owns only the polling thread — same shape
    as modules.calendar.notifier.ReminderChecker /
    modules.plugin_agent.promotion_worker.GapPromotionWorker."""

    def __init__(
        self,
        interval_seconds: int = 2,
        uow_factory: Callable[[], MeetingRecordingUnitOfWork] = MeetingRecordingUnitOfWork,
        converter: AudioConverterPort | None = None,
    ) -> None:
        self._interval_seconds = interval_seconds
        self._uow_factory = uow_factory
        self._converter = converter or LocalAudioConverter()
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
            target=self._run, daemon=True, name="meeting-recording-processor"
        )
        self._thread.start()
        logger.info("Meeting recording processor started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Meeting recording processor stopped")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._drain_pending()
            self._stop_event.wait(self._interval_seconds)

    def _drain_pending(self) -> None:
        # Processes everything currently queued before going back to sleep,
        # rather than one item per interval tick regardless of backlog.
        while not self._stop_event.is_set():
            try:
                recording = service_layer.process_next(
                    self._uow_factory,
                    self._converter,
                    settings.meeting_recording_max_duration_seconds,
                )
            except Exception:
                logger.exception("Meeting recording processor tick failed")
                return
            if recording is None:
                return
            logger.info("Processed recording %s -> status=%s", recording.id, recording.status.value)
