from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Callable

from core.config import MEETING_RECORDINGS_DIR, settings
from core.logger import get_logger
from modules.meeting_recorder.domain import (
    AUDIO_FILENAME,
    RAW_FILENAME,
    Recording,
    RecordingStatus,
    SummaryStatus,
    TranscriptStatus,
)
from modules.meeting_recorder.ports import AudioConverterPort, SummarizerPort, TranscriberPort
from modules.meeting_recorder.uow import MeetingRecordingUnitOfWork

logger = get_logger(__name__)


class RecordingSizeLimitExceeded(Exception):
    """Raised by append_chunk when the streaming upload would exceed the
    configured max size. The recording is marked ERROR and its partial raw
    file removed before this is raised — callers (the HTTP layer) just map
    it to a 413 response."""


# --- CRUD used directly by the REST endpoints -------------------------------


def create_recording(uow: MeetingRecordingUnitOfWork, context_label: str | None = None) -> Recording:
    with uow:
        recording = Recording(dir_path="", context_label=context_label)
        recording_id = uow.recordings.add(recording)
        recording.id = recording_id
        recording.dir_path = str(MEETING_RECORDINGS_DIR / str(recording_id))
        Path(recording.dir_path).mkdir(parents=True, exist_ok=True)
        uow.recordings.update(recording)
        uow.commit()
    return recording


def append_chunk(
    uow: MeetingRecordingUnitOfWork,
    recording_id: int,
    chunk: bytes,
    max_size_bytes: int = settings.meeting_recording_max_size_bytes,
) -> int:
    with uow:
        recording = uow.recordings.get(recording_id)
        if recording is None:
            raise ValueError(f"Recording {recording_id} not found")
        if recording.status != RecordingStatus.UPLOADING:
            raise ValueError(
                f"Recording {recording_id} is not accepting audio (status={recording.status.value})"
            )

        new_size = recording.size_bytes + len(chunk)
        if new_size > max_size_bytes:
            recording.status = RecordingStatus.ERROR
            recording.error = "Превышен максимальный размер записи."
            uow.recordings.update(recording)
            uow.commit()
            shutil.rmtree(recording.dir_path, ignore_errors=True)
            raise RecordingSizeLimitExceeded(recording.error)

        with open(recording.raw_path, "ab") as raw_file:
            raw_file.write(chunk)
        recording.size_bytes = new_size
        uow.recordings.update(recording)
        uow.commit()
        return new_size


def finish_recording(uow: MeetingRecordingUnitOfWork, recording_id: int, mic_only: bool) -> Recording:
    with uow:
        recording = uow.recordings.get(recording_id)
        if recording is None:
            raise ValueError(f"Recording {recording_id} not found")
        if recording.status != RecordingStatus.UPLOADING:
            raise ValueError(
                f"Recording {recording_id} was already finished (status={recording.status.value})"
            )
        recording.status = RecordingStatus.PROCESSING
        recording.mic_only = mic_only
        uow.recordings.update(recording)
        uow.commit()
        return recording


def get_recording(uow: MeetingRecordingUnitOfWork, recording_id: int) -> Recording | None:
    with uow:
        return uow.recordings.get(recording_id)


def list_recordings(uow: MeetingRecordingUnitOfWork) -> list[Recording]:
    with uow:
        return uow.recordings.list_all()


def request_delete(uow: MeetingRecordingUnitOfWork, recording_id: int) -> tuple[bool, bool]:
    """Returns (deleted, pending). `pending` means a background job
    (processor or transcriber/summarizer) still owns this recording's
    files — deletion has been flagged rather than performed immediately, and
    that job will finish the cleanup itself once it next checks the flag."""
    dir_path: str | None = None
    with uow:
        recording = uow.recordings.get(recording_id)
        if recording is None:
            return False, False

        job_in_flight = (
            recording.status == RecordingStatus.PROCESSING
            or recording.transcript_status == TranscriptStatus.TRANSCRIBING
            or recording.summary_status == SummaryStatus.GENERATING
        )
        if job_in_flight:
            recording.delete_requested = True
            uow.recordings.update(recording)
            uow.commit()
            return False, True

        uow.recordings.delete(recording_id)
        uow.commit()
        dir_path = recording.dir_path

    if dir_path:
        shutil.rmtree(dir_path, ignore_errors=True)
    return True, False


# --- Background processor step (raw upload -> converted, validated audio) --


def process_next(
    uow_factory: Callable[[], MeetingRecordingUnitOfWork],
    converter: AudioConverterPort,
    max_duration_seconds: float = settings.meeting_recording_max_duration_seconds,
) -> Recording | None:
    """Converts one PROCESSING recording to the final Opus/OGG file and
    independently re-measures its duration via ffprobe — the client's
    self-reported duration is never trusted for the accept/reject decision.
    Re-checks delete_requested right before writing the outcome, so a DELETE
    that arrived mid-conversion is honored instead of being silently
    overwritten by this tick's result.

    Takes a UoW *factory*, like transcribe_next, rather than one UoW: ffmpeg
    conversion is bounded but can still legitimately take minutes (see
    audio_processing._FFMPEG_TIMEOUT_SECONDS) — holding a single sqlite
    connection open for that whole span, for a step that only needs the DB
    at its start and end, is exactly the pattern transcribe_next's own
    docstring already argues against."""
    uow = uow_factory()
    with uow:
        pending = uow.recordings.list_by_status(RecordingStatus.PROCESSING)
        if not pending:
            return None
        recording = pending[0]
        assert recording.id is not None
    recording_id = recording.id

    error_message: str | None = None
    duration: float | None = None
    try:
        converter.convert_to_ogg(recording.raw_path, recording.audio_path)
        duration = converter.probe_duration_seconds(recording.audio_path)
        if duration > max_duration_seconds:
            error_message = (
                f"Запись длиннее максимально допустимой ({max_duration_seconds / 60:.0f} мин)."
            )
    except Exception as exc:
        logger.exception("Processing failed for recording %s", recording_id)
        error_message = f"Не удалось обработать запись: {exc}"

    final_uow = uow_factory()
    with final_uow:
        current = final_uow.recordings.get(recording_id)
        if current is None:
            recording.raw_path.unlink(missing_ok=True)
            recording.audio_path.unlink(missing_ok=True)
            return None

        if current.delete_requested:
            final_uow.recordings.delete(recording_id)
            final_uow.commit()
            shutil.rmtree(current.dir_path, ignore_errors=True)
            return None

        if error_message is not None:
            current.status = RecordingStatus.ERROR
            current.error = error_message
        else:
            current.status = RecordingStatus.READY
            current.duration_seconds = duration
            current.size_bytes = recording.audio_path.stat().st_size
            current.error = None

        final_uow.recordings.update(current)
        final_uow.commit()

    recording.raw_path.unlink(missing_ok=True)
    if error_message is not None:
        recording.audio_path.unlink(missing_ok=True)
    return current


# --- Background transcriber+summarizer step (READY audio -> text) ----------


def transcribe_next(
    uow_factory: Callable[[], MeetingRecordingUnitOfWork],
    transcriber: TranscriberPort,
    summarizer: SummarizerPort | None,
) -> Recording | None:
    """Claims the next READY recording awaiting transcription and processes
    it fully (transcript, then summary). Unlike the rest of this module's
    service-layer functions, this one takes a UoW *factory* rather than a
    single UoW: a near-max-length recording can take minutes to transcribe,
    and progress is reported incrementally as it goes (see
    modules.meeting_recorder.ports.TranscriberPort.on_progress) — holding
    one sqlite transaction open for that whole duration would be needless
    and out of step with every other short-lived-connection use in this
    codebase, so each DB touch here (claim, each progress tick, final write)
    opens and closes its own short UoW instead.

    A transcription or summary failure never touches `status`/the audio
    file — the recording stays READY and playable regardless.

    Also picks up a recording whose transcript is already DONE but whose
    summary is stuck PENDING (see MeetingRecordingRepository.
    list_pending_summary_only) — the only way to reach that state is
    recover_after_restart resetting a summary that crashed mid-GENERATING;
    without this second claim query, such a row's transcript_status is
    DONE, not PENDING, so the ordinary claim query above would never see
    it again and the summary would stay stuck forever. That case skips
    re-transcribing (reads the already-written transcript file back
    instead) and only redoes the summarization step."""
    uow = uow_factory()
    with uow:
        pending = uow.recordings.list_ready_pending_transcript()
        needs_transcript = bool(pending)
        if not pending:
            pending = uow.recordings.list_pending_summary_only()
        if not pending:
            return None
        recording = pending[0]
        assert recording.id is not None
        if needs_transcript:
            recording.transcript_status = TranscriptStatus.TRANSCRIBING
            recording.transcript_progress = 0.0
        else:
            recording.summary_status = SummaryStatus.GENERATING
        uow.recordings.update(recording)
        uow.commit()
    recording_id = recording.id

    def on_progress(fraction: float) -> None:
        progress_uow = uow_factory()
        with progress_uow:
            current = progress_uow.recordings.get(recording_id)
            if current is None or current.delete_requested:
                return
            current.transcript_progress = fraction
            progress_uow.recordings.update(current)
            progress_uow.commit()

    transcript_text: str | None = None
    transcript_error: str | None = None
    if needs_transcript:
        try:
            transcript_text = transcriber.transcribe(recording.audio_path, on_progress=on_progress)
        except Exception as exc:
            logger.exception("Transcription failed for recording %s", recording_id)
            transcript_error = str(exc)
    else:
        try:
            transcript_text = recording.transcript_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.exception("Could not re-read existing transcript for recording %s", recording_id)
            transcript_error = str(exc)

    summary_text: str | None = None
    summary_error: str | None = None
    summary_status = SummaryStatus.SKIPPED
    if transcript_error is None and transcript_text and summarizer is not None:
        summary_status = SummaryStatus.GENERATING
        try:
            summary_text = asyncio.run(summarizer.summarize(transcript_text))
        except Exception as exc:
            logger.exception("Summary generation failed for recording %s", recording_id)
            summary_error = str(exc)
            summary_status = SummaryStatus.ERROR
    elif transcript_error is not None and not needs_transcript:
        # A summary-only retry (transcript_status was already DONE) whose
        # re-read of the existing transcript file failed — a genuine
        # failure, unlike the "nothing to summarize from" case SKIPPED
        # otherwise means, so it's surfaced as an error instead.
        summary_status = SummaryStatus.ERROR
        summary_error = transcript_error

    final_uow = uow_factory()
    with final_uow:
        current = final_uow.recordings.get(recording_id)
        if current is None:
            return None
        if current.delete_requested:
            final_uow.recordings.delete(recording_id)
            final_uow.commit()
            shutil.rmtree(current.dir_path, ignore_errors=True)
            return None

        if needs_transcript:
            if transcript_error is not None:
                current.transcript_status = TranscriptStatus.ERROR
                current.transcript_error = transcript_error
                current.summary_status = SummaryStatus.SKIPPED
                final_uow.recordings.update(current)
                final_uow.commit()
                return current
            current.transcript_status = TranscriptStatus.DONE
            current.transcript_progress = 1.0
            current.transcript_error = None
            current.transcript_path.write_text(transcript_text or "", encoding="utf-8")

        if summary_text is not None:
            current.summary_status = SummaryStatus.DONE
            current.summary_error = None
            current.summary_path.write_text(summary_text, encoding="utf-8")
        else:
            current.summary_status = summary_status
            current.summary_error = summary_error

        final_uow.recordings.update(current)
        final_uow.commit()
        return current


# --- Startup recovery (see core/main.py's lifespan) -------------------------


def recover_after_restart(uow: MeetingRecordingUnitOfWork) -> None:
    """Any row still UPLOADING or PROCESSING at process startup was
    necessarily orphaned by a previous crash/restart — this process hasn't
    run anything yet, so nothing could have been actively working on it.
    Those can't be safely resumed (an interrupted streaming upload or a
    half-written conversion isn't something to pick back up), so they're
    marked ERROR and their partial raw/converted files removed, while the
    row itself is kept so the failure is visible in the list instead of the
    recording silently vanishing.

    A row stuck TRANSCRIBING or GENERATING (a summary), by contrast, still
    has its converted source audio intact on disk and both are fully
    re-derivable from it — so those are simply reset to PENDING for the
    background workers to retry from scratch, rather than treated as
    errors."""
    orphaned_dirs: list[str] = []
    with uow:
        for recording in [
            *uow.recordings.list_by_status(RecordingStatus.UPLOADING),
            *uow.recordings.list_by_status(RecordingStatus.PROCESSING),
        ]:
            recording.status = RecordingStatus.ERROR
            recording.error = "Запись прервана перезапуском сервера."
            uow.recordings.update(recording)
            orphaned_dirs.append(recording.dir_path)

        for recording in uow.recordings.list_all():
            changed = False
            if recording.transcript_status == TranscriptStatus.TRANSCRIBING:
                recording.transcript_status = TranscriptStatus.PENDING
                recording.transcript_progress = 0.0
                changed = True
            if recording.summary_status == SummaryStatus.GENERATING:
                recording.summary_status = SummaryStatus.PENDING
                changed = True
            if changed:
                uow.recordings.update(recording)

        uow.commit()

    for dir_path in orphaned_dirs:
        (Path(dir_path) / RAW_FILENAME).unlink(missing_ok=True)
        (Path(dir_path) / AUDIO_FILENAME).unlink(missing_ok=True)


def cleanup_orphaned_directories(uow: MeetingRecordingUnitOfWork) -> None:
    """Removes any directory under MEETING_RECORDINGS_DIR that doesn't
    correspond to a known row — e.g. one left behind if the process died
    between creating the directory and committing the row that references
    it."""
    with uow:
        known_ids = {recording.id for recording in uow.recordings.list_all()}

    if not MEETING_RECORDINGS_DIR.is_dir():
        return
    for child in MEETING_RECORDINGS_DIR.iterdir():
        if not child.is_dir():
            continue
        try:
            child_id = int(child.name)
        except ValueError:
            continue
        if child_id not in known_ids:
            shutil.rmtree(child, ignore_errors=True)
