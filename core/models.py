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
    # Waiting for the activation phrase ("привет"/"эй джарвис"/custom — see
    # core/voice/wake_word.py.resolve_wake_phrases), before a command turn
    # starts. Set at the top of every non-paused pass through
    # core/voice/pipeline.py._wait_for_wake_or_pause; once the phrase is
    # heard the loop moves on to LISTENING (the same "actively listening for
    # a command" state as pressing "Начать разговор"), so this exists only
    # to give the background-waiting phase its own distinct CentralOrb look.
    BACKGROUND_LISTENING = "background_listening"
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


# CommandDispatcher._execute's fallback for handlers with nothing more
# specific to say (see that method's docstring comment) — a sentinel, not
# just copy: core.voice.responses.localize_response compares response.message
# against this exact string to decide whether to speak it verbatim or fall
# back to a per-status template, so this and that module's import of it must
# stay the same string. Frontend paths that display response.message
# directly (CommandPanel, TextChat's confirm flow) show this text as-is if a
# handler didn't set anything more specific — it must read as real Russian,
# not just avoid crashing.
GENERIC_EXECUTED_MESSAGE = "Команда выполнена."

# CommandDispatcher._execute's fallback message on failure, used only when
# the caught exception isn't one of our own deliberately-raised, already-
# Russian business errors (ValueError/RuntimeError — see that method's own
# comment) — i.e. an unexpected exception from a library/OS call, which
# would otherwise surface its raw (often English, sometimes a stack-trace
# fragment) str() straight to the user: shown as on-screen error text
# (CommandPanel, TextChat) and, worse, spoken aloud by TTS
# (VoiceRecorder.tsx's handleConfirm) since neither path runs response.message
# through core.voice.responses.localize_response before displaying/speaking
# it. The real exception is still fully logged via logger.exception right
# where this is used, for debugging — this constant is only what the user
# sees/hears.
GENERIC_FAILED_MESSAGE = "Не удалось выполнить команду."


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


class CommandParamField(BaseModel):
    name: str
    type: str
    label: str
    min: float | None = None
    max: float | None = None
    options: list[str] | None = None
    optional: bool = False


class CommandButtonDescriptor(BaseModel):
    name: str
    label: str
    icon: str
    dangerous: bool
    description: str
    params_schema: list[CommandParamField] | None = None


class VoiceLoopStatus(BaseModel):
    running: bool


class AIBridgeStatus(BaseModel):
    active_provider: str
    order: list[str]
    last_reset_date: str
    limit_reached: dict[str, bool]
    logged_in: dict[str, bool] = {}


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


class WordPressUploadResponse(BaseModel):
    job_id: str


class WordPressJobStatusResponse(BaseModel):
    job_id: str
    status: str
    message: str
    edit_url: str | None = None


class CustomCommandResponse(BaseModel):
    id: str
    trigger_phrase: str
    action_type: str
    action_payload: dict[str, Any]
    created_at: str


class CustomCommandListResponse(BaseModel):
    commands: list[CustomCommandResponse]


class QuizletAuthStatus(BaseModel):
    logged_in: bool


class TermPairRequest(BaseModel):
    term: str
    definition: str


class SaveStudySetRequest(BaseModel):
    set_id: str | None = None
    title: str
    terms: list[TermPairRequest]


class TermResponse(BaseModel):
    id: str
    term: str
    definition: str
    times_seen: int
    times_correct: int
    times_wrong: int
    learned: bool


class StudySetResponse(BaseModel):
    id: str
    title: str
    source: str
    quizlet_set_id: str | None
    created_at: str
    progress_percent: int
    attempts_count: int
    terms: list[TermResponse]


class StudySetListResponse(BaseModel):
    sets: list[StudySetResponse]


class LibrarySetResponse(BaseModel):
    quizlet_set_id: str
    title: str
    term_count: int
    already_imported: bool
    local_set_id: str | None


class QuizletLibraryResponse(BaseModel):
    sets: list[LibrarySetResponse]


class BoardGameStartRequest(BaseModel):
    kind: str  # "chess" | "checkers"
    difficulty: str | None = None  # "very_easy".."impossible" (modules.board_games.domain.Difficulty) or None


class BoardGameMoveRequest(BaseModel):
    notation: str  # must be one of the current state's legal_moves


class LegalMoveSquares(BaseModel):
    from_square: str
    to_square: str
    label: str


class BoardGameStateResponse(BaseModel):
    kind: str
    difficulty: str | None
    board_svg: str
    legal_moves: list[str]
    legal_move_squares: list[LegalMoveSquares]
    is_over: bool
    is_check: bool
    result: str | None  # None while ongoing — "1-0"/"0-1"/"1/2-1/2"/"-" (draw) once over
    last_player_move: str | None = None
    last_engine_move: str | None = None
    # The engine's own from/to squares — unlike the player's move (whose
    # origin the frontend already knows, from whichever square they
    # clicked), there's no other way for BoardGamesPanel.tsx to know where
    # the engine's piece started, needed to animate its reply the same way
    # the player's own move is (see modules.board_games.domain.EngineMove).
    last_engine_move_from: str | None = None
    last_engine_move_to: str | None = None
    mistake_message: str | None = None


class GameStartRequest(BaseModel):
    set_id: str
    mode: str


class GameStateResponse(BaseModel):
    session_id: str
    state: dict[str, Any]


class GameAnswerRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class VoiceGameStartResponse(BaseModel):
    session_id: str
    finished: bool
    term_text: str | None
    term_audio_base64: str | None
    remaining: int
    total: int


class VoiceGameAnswerResponse(BaseModel):
    session_id: str
    transcribed_text: str
    correct: bool
    answered_term: str
    expected_definition: str
    result_audio_base64: str | None
    finished: bool
    next_term_text: str | None
    next_term_audio_base64: str | None
    remaining: int
    total: int
