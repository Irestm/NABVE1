from __future__ import annotations

from modules.meeting_recorder.domain import (
    Recording,
    RecordingStatus,
    SummaryStatus,
    TranscriptStatus,
)
from modules.meeting_recorder.uow import MeetingRecordingUnitOfWork


def test_add_sets_created_at_on_the_passed_in_object(tmp_path) -> None:
    # Regression: add() used to only compute created_at locally for the
    # INSERT and never write it back onto `item` — the object returned by
    # service_layer.create_recording (which keeps and reuses it, unlike
    # e.g. modules.calendar's callers, which all discard it) stayed with
    # created_at=None until an explicit get() re-fetched the row.
    db_path = tmp_path / "assistant.db"
    uow = MeetingRecordingUnitOfWork(db_path)
    with uow:
        item = Recording(dir_path="/tmp/rec-created-at")
        assert item.created_at is None
        uow.recordings.add(item)
        assert item.created_at is not None
        uow.commit()


def test_add_get_update_roundtrip_through_real_sqlite(tmp_path) -> None:
    db_path = tmp_path / "assistant.db"
    uow = MeetingRecordingUnitOfWork(db_path)
    with uow:
        recording_id = uow.recordings.add(Recording(dir_path="/tmp/rec-1", context_label="1:1 с Ирой"))
        uow.commit()

    with uow:
        stored = uow.recordings.get(recording_id)
        assert stored is not None
        assert stored.dir_path == "/tmp/rec-1"
        assert stored.context_label == "1:1 с Ирой"
        assert stored.status == RecordingStatus.UPLOADING
        assert stored.transcript_status == TranscriptStatus.PENDING
        assert stored.summary_status == SummaryStatus.PENDING

        stored.status = RecordingStatus.READY
        stored.duration_seconds = 123.5
        stored.size_bytes = 4096
        stored.transcript_status = TranscriptStatus.DONE
        stored.summary_status = SummaryStatus.DONE
        uow.recordings.update(stored)
        uow.commit()

    with uow:
        updated = uow.recordings.get(recording_id)
        assert updated.status == RecordingStatus.READY
        assert updated.duration_seconds == 123.5
        assert updated.size_bytes == 4096
        assert updated.transcript_status == TranscriptStatus.DONE
        assert updated.summary_status == SummaryStatus.DONE


def test_list_by_status_and_list_ready_pending_transcript(tmp_path) -> None:
    db_path = tmp_path / "assistant.db"
    uow = MeetingRecordingUnitOfWork(db_path)
    with uow:
        processing_id = uow.recordings.add(Recording(dir_path="/tmp/a", status=RecordingStatus.PROCESSING))
        ready_id = uow.recordings.add(Recording(dir_path="/tmp/b", status=RecordingStatus.READY))
        ready_transcribed_id = uow.recordings.add(
            Recording(
                dir_path="/tmp/c",
                status=RecordingStatus.READY,
                transcript_status=TranscriptStatus.DONE,
            )
        )
        uow.commit()

    with uow:
        processing = uow.recordings.list_by_status(RecordingStatus.PROCESSING)
        assert [r.id for r in processing] == [processing_id]

        pending_transcript = uow.recordings.list_ready_pending_transcript()
        assert [r.id for r in pending_transcript] == [ready_id]
        assert ready_transcribed_id not in [r.id for r in pending_transcript]


def test_list_ready_pending_transcript_excludes_delete_requested(tmp_path) -> None:
    db_path = tmp_path / "assistant.db"
    uow = MeetingRecordingUnitOfWork(db_path)
    with uow:
        recording_id = uow.recordings.add(
            Recording(dir_path="/tmp/d", status=RecordingStatus.READY, delete_requested=True)
        )
        uow.commit()

    with uow:
        assert uow.recordings.list_ready_pending_transcript() == []
        stored = uow.recordings.get(recording_id)
        assert stored.delete_requested is True


def test_delete_removes_row(tmp_path) -> None:
    db_path = tmp_path / "assistant.db"
    uow = MeetingRecordingUnitOfWork(db_path)
    with uow:
        recording_id = uow.recordings.add(Recording(dir_path="/tmp/e"))
        uow.commit()

    with uow:
        assert uow.recordings.delete(recording_id) is True
        uow.commit()

    with uow:
        assert uow.recordings.get(recording_id) is None
        assert uow.recordings.delete(recording_id) is False
