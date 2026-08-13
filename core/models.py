from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AssistantState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"
    # First-run "getting acquainted" interview — see
    # modules/user_profile/onboarding.py and core/voice/pipeline.py.
    ONBOARDING = "onboarding"
    # The user said their configured stop word (see
    # modules/user_profile/onboarding.py._ask_stop_word) — the assistant
    # ignores the wake word and everything else until the same word is said
    # again (see core/voice/pipeline.py._wait_for_wake_or_pause).
    PAUSED = "paused"


class CommandRequest(BaseModel):
    command: str = Field(..., min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class ConfirmRequest(BaseModel):
    token: str = Field(..., min_length=1)
    approved: bool = True


class CommandStatus(str, Enum):
    EXECUTED = "executed"
    CONFIRMATION_REQUIRED = "confirmation_required"
    CANCELLED = "cancelled"
    FAILED = "failed"


class CommandResponse(BaseModel):
    status: CommandStatus
    command: str
    message: str = ""
    token: str | None = None
    result: dict[str, Any] | None = None


class StatusResponse(BaseModel):
    state: AssistantState
    detail: str = ""


class CommandDescriptor(BaseModel):
    name: str
    dangerous: bool
    description: str


class VoiceLoopStatus(BaseModel):
    running: bool


class AIBridgeStatus(BaseModel):
    active_provider: str
    order: list[str]
    last_reset_date: str
    limit_reached: dict[str, bool]


class UIVisibilityRequest(BaseModel):
    action: str | None = None


class ImageRequest(BaseModel):
    # Plain SVG text, not base64 — see core/state.py::StateManager.request_image.
    svg: str | None = None


class TextQueryRequest(BaseModel):
    text: str = Field(..., min_length=1)
    language: str | None = None


class VoiceQueryResponse(BaseModel):
    transcribed_text: str
    reply_text: str
    language: str
    audio_wav_base64: str | None = None
    status: str | None = None
    token: str | None = None


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1)
    language: str = "ru"
    # Preview-only override: synthesize with this Silero speaker instead of
    # the persisted default, without changing the persisted default.
    speaker: str | None = None


class SpeakResponse(BaseModel):
    audio_wav_base64: str | None = None


class LanUrlResponse(BaseModel):
    url: str


class VoiceOption(BaseModel):
    speaker: str
    label: str
    gender: str


class VoiceOptionsResponse(BaseModel):
    voices: list[VoiceOption]
    selected: str


class SelectVoiceRequest(BaseModel):
    speaker: str = Field(..., min_length=1)


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
    # No transcript to summarize from (transcript_status ended in ERROR) —
    # distinct from PENDING so the client doesn't show "waiting" forever.
    SKIPPED = "skipped"


# NOTE: intentionally NOT imported from modules.meeting_recorder.domain
# despite being value-for-value identical to the enums there — importing
# that module from here forces Python to first run
# modules/meeting_recorder/__init__.py (importing any submodule of a
# package always runs its __init__ first), which eagerly builds
# RecordingProcessor/RecordingTranscriber and, transitively, pulls in
# core.dispatcher — which imports this very file. That's a real circular
# import (confirmed: it breaks core.main at import time), not a
# hypothetical one, so the duplication here is deliberate. If this
# genuinely needs single-sourcing later, the fix is to stop
# modules/meeting_recorder/__init__.py from importing the worker classes
# eagerly, not to import across this particular boundary as-is.
class MeetingRecordingCreateRequest(BaseModel):
    context_label: str | None = None


class MeetingRecordingCreateResponse(BaseModel):
    id: int


class MeetingRecordingChunkResponse(BaseModel):
    size_bytes: int


class MeetingRecordingFinishRequest(BaseModel):
    # Client-reported fallback state (system audio capture failed/declined
    # during this recording) — informational only, does not gate anything
    # server-side. Actual duration/size limits are always re-checked
    # independently by the server, never trusted from the client.
    mic_only: bool = False


class MeetingRecordingResponse(BaseModel):
    id: int
    created_at: str
    status: RecordingStatus
    error: str | None = None
    duration_seconds: float | None = None
    size_bytes: int
    mic_only: bool
    context_label: str | None = None
    transcript_status: TranscriptStatus
    transcript_progress: float
    transcript_error: str | None = None
    summary_status: SummaryStatus
    summary_error: str | None = None


class MeetingRecordingDeleteResponse(BaseModel):
    deleted: bool
    # True if the record couldn't be removed immediately because its
    # background job (conversion/transcription) was still running — it was
    # instead flagged for cleanup once that job notices and finishes.
    pending: bool = False


class MeetingTranscriptResponse(BaseModel):
    text: str


class MeetingSummaryResponse(BaseModel):
    text: str


# --- modules/messaging bridge (see modules/messaging/BRIDGE.md) — used by
# an external delivery process (e.g. a separate Telegram bot project), not
# by the frontend. ---
class MessagingIncomingRequest(BaseModel):
    source: str
    sender_identifier: str
    sender_label: str
    text: str


class MessagingIncomingResponse(BaseModel):
    recorded: bool
    message_id: int | None = None


class MessagingOutboundItem(BaseModel):
    id: int
    source: str
    recipient_identifier: str
    text: str
    created_at: str


class MessagingOutboundAckRequest(BaseModel):
    status: str  # "sent" or "failed"
