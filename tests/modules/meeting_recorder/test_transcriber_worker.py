from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from modules.meeting_recorder.transcriber_worker import RecordingTranscriber


class _FakeStatus(Enum):
    DONE = "done"


@dataclass
class _FakeRecording:
    id: int
    transcript_status: _FakeStatus = _FakeStatus.DONE
    summary_status: _FakeStatus = _FakeStatus.DONE


class _FakeTranscriber:
    def transcribe(self, audio_path, *, on_progress):  # pragma: no cover - not exercised
        raise AssertionError("should not be called by these tests")


class _FakeSummarizer:
    async def summarize(self, transcript_text: str) -> str:  # pragma: no cover - not exercised
        raise AssertionError("should not be called by these tests")


def test_is_running_false_before_start_and_true_after(monkeypatch) -> None:
    import modules.meeting_recorder.transcriber_worker as worker_module

    monkeypatch.setattr(worker_module.service_layer, "transcribe_next", lambda *a, **k: None)

    transcriber = RecordingTranscriber(transcriber=_FakeTranscriber(), summarizer=_FakeSummarizer())
    assert transcriber.is_running is False

    transcriber.start()
    try:
        assert transcriber.is_running is True
    finally:
        transcriber.stop()
    assert transcriber.is_running is False


def test_start_is_idempotent_while_already_running(monkeypatch) -> None:
    import modules.meeting_recorder.transcriber_worker as worker_module

    monkeypatch.setattr(worker_module.service_layer, "transcribe_next", lambda *a, **k: None)

    transcriber = RecordingTranscriber(transcriber=_FakeTranscriber(), summarizer=_FakeSummarizer())
    transcriber.start()
    try:
        first_thread = transcriber._thread
        transcriber.start()
        assert transcriber._thread is first_thread
    finally:
        transcriber.stop()


def test_drain_pending_processes_everything_queued_before_returning(monkeypatch) -> None:
    import modules.meeting_recorder.transcriber_worker as worker_module

    results = iter([_FakeRecording(id=1), _FakeRecording(id=2), None])
    calls: list[int] = []

    def fake_transcribe_next(uow_factory, transcriber, summarizer):
        value = next(results)
        if value is not None:
            calls.append(value.id)
        return value

    monkeypatch.setattr(worker_module.service_layer, "transcribe_next", fake_transcribe_next)

    transcriber = RecordingTranscriber(transcriber=_FakeTranscriber(), summarizer=_FakeSummarizer())
    transcriber._drain_pending()

    assert calls == [1, 2]


def test_drain_pending_stops_and_logs_on_exception_instead_of_crashing(monkeypatch) -> None:
    import modules.meeting_recorder.transcriber_worker as worker_module

    def fake_transcribe_next(uow_factory, transcriber, summarizer):
        raise RuntimeError("simulated transcription failure")

    monkeypatch.setattr(worker_module.service_layer, "transcribe_next", fake_transcribe_next)

    transcriber = RecordingTranscriber(transcriber=_FakeTranscriber(), summarizer=_FakeSummarizer())
    transcriber._drain_pending()  # must not raise


def test_stop_before_start_is_a_safe_noop() -> None:
    transcriber = RecordingTranscriber(transcriber=_FakeTranscriber(), summarizer=_FakeSummarizer())
    transcriber.stop()  # must not raise
    assert transcriber.is_running is False
