from __future__ import annotations

from modules.meeting_recorder.processor import RecordingProcessor
from modules.meeting_recorder.transcriber_worker import RecordingTranscriber

recording_processor = RecordingProcessor()
recording_transcriber = RecordingTranscriber()

__all__ = ["recording_processor", "recording_transcriber"]
