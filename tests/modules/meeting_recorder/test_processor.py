from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from modules.meeting_recorder.processor import RecordingProcessor


class _FakeStatus(Enum):
    READY = "ready"


@dataclass
class _FakeRecording:
    id: int
    status: _FakeStatus = _FakeStatus.READY


class _FakeConverter:
    def convert_to_ogg(self, raw_path, output_path) -> None:  # pragma: no cover - not exercised
        raise AssertionError("should not be called by these tests")

    def probe_duration_seconds(self, path) -> float:  # pragma: no cover - not exercised
        raise AssertionError("should not be called by these tests")


def test_is_running_false_before_start_and_true_after(monkeypatch) -> None:
    processor = RecordingProcessor(converter=_FakeConverter())
    assert processor.is_running is False

    # Avoid real polling work: make service_layer.process_next a no-op that
    # always reports "nothing pending" so _drain_pending returns instantly.
    import modules.meeting_recorder.processor as processor_module

    monkeypatch.setattr(processor_module.service_layer, "process_next", lambda *a, **k: None)

    processor.start()
    try:
        assert processor.is_running is True
    finally:
        processor.stop()
    assert processor.is_running is False


def test_start_is_idempotent_while_already_running(monkeypatch) -> None:
    import modules.meeting_recorder.processor as processor_module

    monkeypatch.setattr(processor_module.service_layer, "process_next", lambda *a, **k: None)

    processor = RecordingProcessor(converter=_FakeConverter())
    processor.start()
    try:
        first_thread = processor._thread
        processor.start()  # must not spawn a second thread
        assert processor._thread is first_thread
    finally:
        processor.stop()


def test_drain_pending_processes_everything_queued_before_returning(monkeypatch) -> None:
    import modules.meeting_recorder.processor as processor_module

    results = iter([_FakeRecording(id=1), _FakeRecording(id=2), None])  # two, then nothing left
    calls: list[int] = []

    def fake_process_next(uow_factory, converter, max_duration_seconds):
        value = next(results)
        if value is not None:
            calls.append(value.id)
        return value

    monkeypatch.setattr(processor_module.service_layer, "process_next", fake_process_next)

    processor = RecordingProcessor(converter=_FakeConverter())
    processor._drain_pending()

    assert calls == [1, 2]


def test_drain_pending_stops_and_logs_on_exception_instead_of_crashing(monkeypatch) -> None:
    import modules.meeting_recorder.processor as processor_module

    def fake_process_next(uow_factory, converter, max_duration_seconds):
        raise RuntimeError("simulated DB error")

    monkeypatch.setattr(processor_module.service_layer, "process_next", fake_process_next)

    processor = RecordingProcessor(converter=_FakeConverter())
    processor._drain_pending()  # must not raise


def test_stop_before_start_is_a_safe_noop() -> None:
    processor = RecordingProcessor(converter=_FakeConverter())
    processor.stop()  # must not raise
    assert processor.is_running is False
