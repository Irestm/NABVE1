from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

import pytest

from modules.meeting_recorder import service_layer
from modules.meeting_recorder.domain import (
    Recording,
    RecordingStatus,
    SummaryStatus,
    TranscriptStatus,
)


class FakeMeetingRecordingRepository:
    def __init__(self) -> None:
        self._items: dict[int, Recording] = {}
        self._next_id = 1

    def add(self, item: Recording) -> int:
        item.id = self._next_id
        item.created_at = item.created_at or datetime.now()
        self._items[self._next_id] = item
        self._next_id += 1
        return item.id

    def get(self, key: int) -> Recording | None:
        return self._items.get(key)

    def list_all(self) -> list[Recording]:
        return sorted(self._items.values(), key=lambda r: r.created_at, reverse=True)

    def list_by_status(self, status: RecordingStatus) -> list[Recording]:
        return [r for r in self._items.values() if r.status == status]

    def list_ready_pending_transcript(self) -> list[Recording]:
        return [
            r
            for r in self._items.values()
            if r.status == RecordingStatus.READY
            and r.transcript_status == TranscriptStatus.PENDING
            and not r.delete_requested
        ]

    def list_pending_summary_only(self) -> list[Recording]:
        return [
            r
            for r in self._items.values()
            if r.status == RecordingStatus.READY
            and r.transcript_status == TranscriptStatus.DONE
            and r.summary_status == SummaryStatus.PENDING
            and not r.delete_requested
        ]

    def update(self, item: Recording) -> None:
        assert item.id is not None
        self._items[item.id] = item

    def delete(self, key: int) -> bool:
        return self._items.pop(key, None) is not None


class FakeMeetingRecordingUnitOfWork:
    def __init__(self, repo: FakeMeetingRecordingRepository) -> None:
        self.recordings = repo

    def __enter__(self) -> "FakeMeetingRecordingUnitOfWork":
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


class FakeConverter:
    def __init__(self, duration_seconds: float = 12.5, fail: bool = False) -> None:
        self.duration_seconds = duration_seconds
        self.fail = fail

    def convert_to_ogg(self, raw_path: Path, output_path: Path) -> None:
        if self.fail:
            raise RuntimeError("conversion boom")
        output_path.write_bytes(b"fake-ogg-audio")

    def probe_duration_seconds(self, path: Path) -> float:
        return self.duration_seconds


class FakeTranscriber:
    def __init__(self, text: str = "привет мир", fail: bool = False) -> None:
        self.text = text
        self.fail = fail

    def transcribe(self, audio_path: Path, *, on_progress) -> str:
        if self.fail:
            raise RuntimeError("stt boom")
        on_progress(0.5)
        on_progress(1.0)
        return self.text


class FakeSummarizer:
    def __init__(self, text: str = "Краткое саммари", fail: bool = False) -> None:
        self.text = text
        self.fail = fail

    async def summarize(self, transcript_text: str) -> str:
        if self.fail:
            raise RuntimeError("summary boom")
        return self.text


@pytest.fixture()
def repo() -> FakeMeetingRecordingRepository:
    return FakeMeetingRecordingRepository()


@pytest.fixture()
def uow_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repo: FakeMeetingRecordingRepository
) -> Callable[[], FakeMeetingRecordingUnitOfWork]:
    recordings_dir = tmp_path / "meeting_recordings"
    recordings_dir.mkdir()
    monkeypatch.setattr(service_layer, "MEETING_RECORDINGS_DIR", recordings_dir)
    return lambda: FakeMeetingRecordingUnitOfWork(repo)


def test_create_recording_creates_directory(uow_factory, repo) -> None:
    recording = service_layer.create_recording(uow_factory(), context_label="Sync с командой")
    assert recording.id is not None
    assert Path(recording.dir_path).is_dir()
    assert recording.status == RecordingStatus.UPLOADING
    assert recording.context_label == "Sync с командой"


def test_append_chunk_accumulates_size_and_writes_raw_file(uow_factory) -> None:
    recording = service_layer.create_recording(uow_factory(), None)
    size1 = service_layer.append_chunk(uow_factory(), recording.id, b"abc", max_size_bytes=100)
    size2 = service_layer.append_chunk(uow_factory(), recording.id, b"defgh", max_size_bytes=100)
    assert size1 == 3
    assert size2 == 8
    assert recording.raw_path.read_bytes() == b"abcdefgh"


def test_append_chunk_over_limit_marks_error_and_removes_files(uow_factory, repo) -> None:
    recording = service_layer.create_recording(uow_factory(), None)
    with pytest.raises(service_layer.RecordingSizeLimitExceeded):
        service_layer.append_chunk(uow_factory(), recording.id, b"x" * 10, max_size_bytes=5)
    stored = repo.get(recording.id)
    assert stored.status == RecordingStatus.ERROR
    assert not Path(recording.dir_path).exists()


def test_append_chunk_rejects_once_not_uploading(uow_factory) -> None:
    recording = service_layer.create_recording(uow_factory(), None)
    service_layer.finish_recording(uow_factory(), recording.id, mic_only=False)
    with pytest.raises(ValueError):
        service_layer.append_chunk(uow_factory(), recording.id, b"abc", max_size_bytes=100)


def test_finish_recording_transitions_to_processing(uow_factory) -> None:
    recording = service_layer.create_recording(uow_factory(), None)
    finished = service_layer.finish_recording(uow_factory(), recording.id, mic_only=True)
    assert finished.status == RecordingStatus.PROCESSING
    assert finished.mic_only is True


def _uploaded_and_finished(uow_factory) -> Recording:
    recording = service_layer.create_recording(uow_factory(), None)
    service_layer.append_chunk(uow_factory(), recording.id, b"raw-audio-bytes", max_size_bytes=10_000)
    return service_layer.finish_recording(uow_factory(), recording.id, mic_only=False)


def test_process_next_success_marks_ready_and_removes_raw(uow_factory) -> None:
    recording = _uploaded_and_finished(uow_factory)
    result = service_layer.process_next(uow_factory,FakeConverter(duration_seconds=42.0), 9000)
    assert result.status == RecordingStatus.READY
    assert result.duration_seconds == 42.0
    assert not recording.raw_path.exists()
    assert recording.audio_path.exists()


def test_process_next_rejects_over_max_duration(uow_factory) -> None:
    recording = _uploaded_and_finished(uow_factory)
    result = service_layer.process_next(uow_factory,FakeConverter(duration_seconds=99_999.0), 9000)
    assert result.status == RecordingStatus.ERROR
    assert "максимально" in result.error
    assert not recording.raw_path.exists()
    assert not recording.audio_path.exists()


def test_process_next_converter_failure_marks_error(uow_factory) -> None:
    _uploaded_and_finished(uow_factory)
    result = service_layer.process_next(uow_factory,FakeConverter(fail=True), 9000)
    assert result.status == RecordingStatus.ERROR


def test_process_next_honors_delete_requested_mid_conversion(uow_factory, repo) -> None:
    recording = _uploaded_and_finished(uow_factory)

    deleted, pending = service_layer.request_delete(uow_factory(), recording.id)
    assert (deleted, pending) == (False, True)

    result = service_layer.process_next(uow_factory,FakeConverter(duration_seconds=5.0), 9000)
    assert result is None
    assert repo.get(recording.id) is None
    assert not Path(recording.dir_path).exists()


def test_request_delete_is_immediate_when_no_job_in_flight(uow_factory, repo) -> None:
    recording = service_layer.create_recording(uow_factory(), None)
    deleted, pending = service_layer.request_delete(uow_factory(), recording.id)
    assert (deleted, pending) == (True, False)
    assert repo.get(recording.id) is None
    assert not Path(recording.dir_path).exists()


def test_request_delete_unknown_recording_returns_false_false(uow_factory) -> None:
    assert service_layer.request_delete(uow_factory(), 999) == (False, False)


def _ready_recording(uow_factory) -> Recording:
    recording = _uploaded_and_finished(uow_factory)
    service_layer.process_next(uow_factory,FakeConverter(duration_seconds=3.0), 9000)
    return recording


def test_transcribe_next_success_writes_transcript_and_summary(uow_factory) -> None:
    recording = _ready_recording(uow_factory)
    result = service_layer.transcribe_next(
        uow_factory, FakeTranscriber(text="Привет, это тест."), FakeSummarizer(text="Саммари теста.")
    )
    assert result.transcript_status == TranscriptStatus.DONE
    assert result.transcript_progress == 1.0
    assert recording.transcript_path.read_text(encoding="utf-8") == "Привет, это тест."
    assert result.summary_status == SummaryStatus.DONE
    assert recording.summary_path.read_text(encoding="utf-8") == "Саммари теста."


def test_transcribe_next_failure_keeps_recording_ready_and_skips_summary(uow_factory) -> None:
    _ready_recording(uow_factory)
    result = service_layer.transcribe_next(uow_factory, FakeTranscriber(fail=True), FakeSummarizer())
    assert result.status == RecordingStatus.READY
    assert result.transcript_status == TranscriptStatus.ERROR
    assert result.summary_status == SummaryStatus.SKIPPED


def test_transcribe_next_summary_failure_keeps_transcript_done(uow_factory) -> None:
    _ready_recording(uow_factory)
    result = service_layer.transcribe_next(uow_factory, FakeTranscriber(), FakeSummarizer(fail=True))
    assert result.transcript_status == TranscriptStatus.DONE
    assert result.summary_status == SummaryStatus.ERROR


def test_transcribe_next_returns_none_when_nothing_pending(uow_factory) -> None:
    assert service_layer.transcribe_next(uow_factory, FakeTranscriber(), FakeSummarizer()) is None


def test_transcribe_next_resumes_summary_only_after_crash_recovery(uow_factory, repo) -> None:
    # Regression: recover_after_restart resets a summary stuck GENERATING
    # back to PENDING while leaving transcript_status DONE (see
    # test_recover_after_restart_resets_stuck_generating_summary_to_pending).
    # Before MeetingRecordingRepository.list_pending_summary_only existed,
    # transcribe_next's only claim query required transcript_status =
    # PENDING, so such a row could never be picked up again and its
    # summary stayed PENDING forever.
    recording = _ready_recording(uow_factory)
    transcriber = FakeTranscriber(text="Уже готовый транскрипт.")
    service_layer.transcribe_next(uow_factory, transcriber, None)  # writes transcript, summary SKIPPED (no summarizer)
    stuck = repo.get(recording.id)
    assert stuck.transcript_status == TranscriptStatus.DONE
    stuck.summary_status = SummaryStatus.PENDING
    repo.update(stuck)

    result = service_layer.transcribe_next(
        uow_factory, transcriber=transcriber, summarizer=FakeSummarizer(text="Саммари после сбоя.")
    )

    assert result is not None
    assert result.transcript_status == TranscriptStatus.DONE
    # Transcript itself must not have been redone/touched a second time.
    assert recording.transcript_path.read_text(encoding="utf-8") == "Уже готовый транскрипт."
    assert result.summary_status == SummaryStatus.DONE
    assert recording.summary_path.read_text(encoding="utf-8") == "Саммари после сбоя."


def test_transcribe_next_summary_only_retry_errors_if_transcript_file_missing(uow_factory, repo) -> None:
    recording = _ready_recording(uow_factory)
    service_layer.transcribe_next(uow_factory, FakeTranscriber(text="x"), None)
    stuck = repo.get(recording.id)
    stuck.summary_status = SummaryStatus.PENDING
    repo.update(stuck)
    recording.transcript_path.unlink()  # simulate the file having gone missing

    result = service_layer.transcribe_next(uow_factory, FakeTranscriber(), FakeSummarizer())

    assert result.summary_status == SummaryStatus.ERROR
    assert result.summary_error


def test_recover_after_restart_fails_orphaned_uploads_and_processing(uow_factory, repo) -> None:
    uploading = service_layer.create_recording(uow_factory(), None)
    service_layer.append_chunk(uow_factory(), uploading.id, b"partial", max_size_bytes=1000)

    processing = _uploaded_and_finished(uow_factory)

    service_layer.recover_after_restart(uow_factory())

    assert repo.get(uploading.id).status == RecordingStatus.ERROR
    assert not uploading.raw_path.exists()
    assert repo.get(processing.id).status == RecordingStatus.ERROR
    assert not processing.raw_path.exists()


def test_recover_after_restart_resets_stuck_transcribing_to_pending(uow_factory, repo) -> None:
    recording = _ready_recording(uow_factory)
    stuck = repo.get(recording.id)
    stuck.transcript_status = TranscriptStatus.TRANSCRIBING
    stuck.transcript_progress = 0.4
    repo.update(stuck)

    service_layer.recover_after_restart(uow_factory())

    recovered = repo.get(recording.id)
    assert recovered.status == RecordingStatus.READY
    assert recovered.transcript_status == TranscriptStatus.PENDING
    assert recovered.transcript_progress == 0.0


def test_cleanup_orphaned_directories_removes_unknown_dirs_keeps_known(uow_factory, repo) -> None:
    recording = service_layer.create_recording(uow_factory(), None)
    orphan_dir = service_layer.MEETING_RECORDINGS_DIR / "9999"
    orphan_dir.mkdir()
    (orphan_dir / "raw.webm").write_bytes(b"leftover")

    service_layer.cleanup_orphaned_directories(uow_factory())

    assert not orphan_dir.exists()
    assert Path(recording.dir_path).exists()


def test_recover_after_restart_resets_stuck_generating_summary_to_pending(uow_factory, repo) -> None:
    recording = _ready_recording(uow_factory)
    stuck = repo.get(recording.id)
    stuck.transcript_status = TranscriptStatus.DONE
    stuck.summary_status = SummaryStatus.GENERATING
    repo.update(stuck)

    service_layer.recover_after_restart(uow_factory())

    recovered = repo.get(recording.id)
    assert recovered.summary_status == SummaryStatus.PENDING
    assert recovered.transcript_status == TranscriptStatus.DONE
