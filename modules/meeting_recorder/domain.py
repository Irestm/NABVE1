from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

RAW_FILENAME = "raw.webm"
AUDIO_FILENAME = "audio.ogg"
TRANSCRIPT_FILENAME = "transcript.txt"
SUMMARY_FILENAME = "summary.txt"

# Long recordings are transcribed in fixed windows rather than one opaque
# whisper call, so transcript_progress can advance incrementally instead of
# staying at 0 for up to ~2h30m worst case.
TRANSCRIPT_CHUNK_SECONDS = 600


class RecordingStatus(str, Enum):
    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"


class TranscriptStatus(str, Enum):
    PENDING = "pending"
    TRANSCRIBING = "transcribing"
    DONE = "done"
    ERROR = "error"


class SummaryStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    DONE = "done"
    ERROR = "error"
    # Transcript itself never finished successfully, so there is nothing to
    # summarize from — distinct from PENDING so the client doesn't show
    # "waiting for summary" forever once the transcript has already failed.
    SKIPPED = "skipped"


@dataclass
class Recording:
    """One meeting recording. `status` tracks the raw-upload -> converted
    audio lifecycle; `transcript_status` and `summary_status` are
    independent phases layered on top of a READY recording — a failure in
    either one never invalidates the saved, already-playable audio."""

    dir_path: str
    id: int | None = None
    created_at: datetime | None = None
    status: RecordingStatus = RecordingStatus.UPLOADING
    error: str | None = None
    # Server-derived (ffprobe), never trusted from the client.
    duration_seconds: float | None = None
    size_bytes: int = 0
    # True if system/meeting audio couldn't be captured and the recording
    # fell back to microphone-only — informational, not an error state.
    mic_only: bool = False
    context_label: str | None = None
    transcript_status: TranscriptStatus = TranscriptStatus.PENDING
    transcript_progress: float = 0.0
    transcript_error: str | None = None
    summary_status: SummaryStatus = SummaryStatus.PENDING
    summary_error: str | None = None
    # Set by a DELETE request that arrived while a background job (processor
    # or transcriber) still owned this row's files. The owning worker checks
    # this flag between steps and performs the actual cleanup once it's safe.
    delete_requested: bool = False

    @property
    def raw_path(self) -> Path:
        return Path(self.dir_path) / RAW_FILENAME

    @property
    def audio_path(self) -> Path:
        return Path(self.dir_path) / AUDIO_FILENAME

    @property
    def transcript_path(self) -> Path:
        return Path(self.dir_path) / TRANSCRIPT_FILENAME

    @property
    def summary_path(self) -> Path:
        return Path(self.dir_path) / SUMMARY_FILENAME
