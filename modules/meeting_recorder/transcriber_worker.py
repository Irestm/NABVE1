from __future__ import annotations

import threading
from typing import Callable

from core.logger import get_logger
from modules.meeting_recorder import service_layer
from modules.meeting_recorder.adapters import LocalFirstSummarizer, LocalWhisperMeetingTranscriber
from modules.meeting_recorder.ports import SummarizerPort, TranscriberPort
from modules.meeting_recorder.uow import MeetingRecordingUnitOfWork

logger = get_logger(__name__)


class RecordingTranscriber:
    """Background poller: transcribes READY recordings and, on success,
    generates a summary (see service_layer.transcribe_next). Runs on its own
    thread/interval, separate from RecordingProcessor, since transcription
    is the slower of the two phases and shouldn't be blocked behind, or
    block, audio conversion of other recordings."""

    def __init__(
        self,
        interval_seconds: int = 3,
        uow_factory: Callable[[], MeetingRecordingUnitOfWork] = MeetingRecordingUnitOfWork,
        transcriber: TranscriberPort | None = None,
        summarizer: SummarizerPort | None = None,
    ) -> None:
        self._interval_seconds = interval_seconds
        self._uow_factory = uow_factory
        self._transcriber = transcriber or LocalWhisperMeetingTranscriber()
        self._summarizer = summarizer or LocalFirstSummarizer()
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
            target=self._run, daemon=True, name="meeting-recording-transcriber"
        )
        self._thread.start()
        logger.info("Meeting recording transcriber started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Meeting recording transcriber stopped")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._drain_pending()
            self._stop_event.wait(self._interval_seconds)

    def _drain_pending(self) -> None:
        while not self._stop_event.is_set():
            try:
                recording = service_layer.transcribe_next(
                    self._uow_factory, self._transcriber, self._summarizer
                )
            except Exception:
                logger.exception("Meeting recording transcriber tick failed")
                return
            if recording is None:
                return
            logger.info(
                "Transcribed recording %s -> transcript_status=%s summary_status=%s",
                recording.id,
                recording.transcript_status.value,
                recording.summary_status.value,
            )
