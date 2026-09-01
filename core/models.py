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
    # The user said their configured stop word (set via
    # frontend/src/components/SettingsPanel.tsx's Профиль tab) — the
    # assistant ignores the wake word and everything else until the same
    # word is said again (see core/voice/pipeline.py._wait_for_wake_or_pause).
    PAUSED = "paused"
    # A critical calendar reminder has taken over: media is paused and the
    # assistant is waiting for a spoken acknowledgement before restoring
    # everything — see core/voice/critical_reminder.py and the orb's
    # attention animation (frontend CentralOrb.css).
    CRITICAL_REMINDER = "critical_reminder"
    # modules/discussion_mode: the assistant is silently listening to a
    # conversation between people, transcribing but not acting on it, until
    # asked for its opinion or told to exit — see core/voice/pipeline.py's
    # _run_discussion_mode.
    DISCUSSION = "discussion"


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


class GestureCalibrationState(BaseModel):
    # modules/gesture_control calibration wizard — one step per gesture, each
    # demonstrated `reps_target` times. Drives the on-screen "5 dots".
    phase_index: int
    total_phases: int
    label: str
    instruction: str
    reps_done: int
    reps_target: int
    done: bool
    phase_key: str = "steady"


class StatusResponse(BaseModel):
    state: AssistantState
    detail: str = ""
    # Name of the currently active voice module context (e.g. "fitness"),
    # or None when no such context is active — see
    # core/voice/module_context.py. CentralOrb.tsx uses this to show a small
    # indicator of which focused mode Jarvis is currently listening in.
    active_module_context: str | None = None
    # modules/gesture_control: whether the webcam gesture mode is on. The
    # frontend uses it only for a small on-screen indicator — the enlarged
    # cursor is the OS's own (gesture_control/cursor_zoom.py), not an overlay.
    gesture_mode_active: bool = False
    # Present only while the gesture calibration wizard is running.
    gesture_calibration: GestureCalibrationState | None = None


class DelayedTaskResponse(BaseModel):
    id: int
    original_text: str
    command_name: str
    # ISO-8601 — the frontend formats the local time itself.
    run_at: str


class ConversationTurnResponse(BaseModel):
    # ISO-8601 UTC string straight from modules/conversation_log — the
    # frontend formats the local time and day separators itself.
    timestamp: str
    role: str
    text: str
    source: str


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
    group: str
    params_schema: list[CommandParamField] | None = None


class VoiceLoopStatus(BaseModel):
    running: bool


class VoiceLoopSignalResult(BaseModel):
    # False means the loop wasn't running to receive the signal (e.g.
    # voice_autostart is off, or it crashed) — distinct from `running` in
    # VoiceLoopStatus, since this reports whether *this specific action*
    # (manual wake / pause) took effect, not just current loop liveness.
    accepted: bool


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


class YouTubeApiKeyRequest(BaseModel):
    api_key: str = Field(..., min_length=1)


class YouTubeStatusResponse(BaseModel):
    key_configured: bool
    units_used: int
    daily_limit: int
    remaining_searches: int
    near_limit: bool
    exhausted: bool


class ApiKeyRequest(BaseModel):
    api_key: str = Field(..., min_length=1)


class GeminiKeyStatusResponse(BaseModel):
    key_configured: bool
    requests_used_today: int
    daily_limit: int


class ClaudeKeyStatusResponse(BaseModel):
    key_configured: bool


class SpotifyClientIdRequest(BaseModel):
    client_id: str = Field(..., min_length=1)


class SpotifyStatusResponse(BaseModel):
    client_id_configured: bool
    connected: bool
    redirect_uri: str


class SpotifyLoginResponse(BaseModel):
    authorize_url: str


class GeneratedImageResponse(BaseModel):
    id: int
    prompt: str
    source: str
    created_at: str


class TranscribeResponse(BaseModel):
    text: str


class GithubPatRequest(BaseModel):
    pat: str = Field(..., min_length=1)


class GithubStatusResponse(BaseModel):
    pat_configured: bool


class TelegramCredentialsRequest(BaseModel):
    api_id: int
    api_hash: str = Field(..., min_length=1)


class TelegramCredentialsStatusResponse(BaseModel):
    configured: bool


class TelegramAccountResponse(BaseModel):
    id: int
    label: str
    phone_number: str
    connected: bool


class TelegramLoginStartRequest(BaseModel):
    label: str = Field(..., min_length=1)
    phone_number: str = Field(..., min_length=1)


class TelegramLoginStartResponse(BaseModel):
    token: str


class TelegramLoginCodeRequest(BaseModel):
    token: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1)


class TelegramLoginCodeResponse(BaseModel):
    needs_password: bool
    account: TelegramAccountResponse | None = None


class TelegramLoginPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class TelegramContactRequest(BaseModel):
    identifier: str = Field(..., min_length=1)
    note: str = ""


class TelegramContactResponse(BaseModel):
    id: int
    identifier: str
    note: str


class PendingMessageResponse(BaseModel):
    id: int
    source: str
    sender_label: str
    text: str
    received_at: str


class FitnessBioProfileResponse(BaseModel):
    sex: str | None
    age: int | None
    height_cm: float | None
    weight_kg: float | None
    bmi: float | None
    bmi_category: str | None
    updated_at: str


class FitnessBioProfileUpdateRequest(BaseModel):
    sex: str | None = None
    age: int | None = None
    height_cm: float | None = None
    weight_kg: float | None = None


class FitnessWeightHistoryEntryResponse(BaseModel):
    weight_kg: float
    recorded_at: str


class FitnessMeasurementResponse(BaseModel):
    id: int
    body_part: str
    value_cm: float
    recorded_at: str


class FitnessMeasurementCreateRequest(BaseModel):
    body_part: str = Field(..., min_length=1)
    value_cm: float


class FitnessGoalResponse(BaseModel):
    id: int
    goal_type: str
    description: str
    target_value: float | None
    unit: str | None
    deadline: str | None
    created_at: str
    achieved_at: str | None


class FitnessGoalCreateRequest(BaseModel):
    goal_type: str
    description: str = Field(..., min_length=1)
    target_value: float | None = None
    unit: str | None = None
    deadline: str | None = None


class FitnessMealResponse(BaseModel):
    id: int
    description: str
    estimated_calories: float | None
    protein_g: float | None
    fat_g: float | None
    carbs_g: float | None
    confidence: str
    source: str
    has_photo: bool
    logged_at: str


class FitnessMealTextRequest(BaseModel):
    description: str = Field(..., min_length=1)
    grams: float | None = None


# progress photos and meal photos deliberately expose no raw filesystem
# path in their REST responses (same privacy-conscious shape
# GeneratedImageResponse already uses for generated images) — the actual
# bytes are served by a dedicated /file endpoint instead, keyed by id.
class FitnessProgressPhotoResponse(BaseModel):
    id: int
    note: str | None
    taken_at: str


class FitnessChatRequest(BaseModel):
    text: str = Field(..., min_length=1)


class FitnessChatResponse(BaseModel):
    reply: str

