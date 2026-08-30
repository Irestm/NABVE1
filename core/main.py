from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core.bootstrap import compose
from core.command_ui_metadata import COMMAND_UI_METADATA
from core.config import BASE_DIR, DATA_DIR, detect_lan_ip, settings
from core.dispatcher import UnknownCommandError
from core.logger import get_logger
from core.message_bus import message_bus
from core.models import (
    AIBridgeStatus,
    ApiKeyRequest,
    BoardGameMoveRequest,
    BoardGameStartRequest,
    BoardGameStateResponse,
    ClaudeKeyStatusResponse,
    CommandButtonDescriptor,
    CommandDescriptor,
    CommandParamField,
    CommandRequest,
    CommandResponse,
    CommandStatus,
    ConfirmRequest,
    ConversationTurnResponse,
    CustomCommandListResponse,
    CustomCommandResponse,
    DelayedTaskResponse,
    FitnessBioProfileResponse,
    FitnessBioProfileUpdateRequest,
    FitnessChatRequest,
    FitnessChatResponse,
    FitnessGoalCreateRequest,
    FitnessGoalResponse,
    FitnessMealResponse,
    FitnessMealTextRequest,
    FitnessMeasurementCreateRequest,
    FitnessMeasurementResponse,
    FitnessProgressPhotoResponse,
    FitnessWeightHistoryEntryResponse,
    GeminiKeyStatusResponse,
    GeneratedImageResponse,
    GithubPatRequest,
    GithubStatusResponse,
    ImageRequest,
    LanUrlResponse,
    LegalMoveSquares,
    MeetingRecordingChunkResponse,
    MeetingRecordingCreateRequest,
    MeetingRecordingCreateResponse,
    MeetingRecordingDeleteResponse,
    MeetingRecordingFinishRequest,
    MeetingRecordingResponse,
    MeetingSummaryResponse,
    MeetingTranscriptResponse,
    MessagingIncomingRequest,
    MessagingIncomingResponse,
    MessagingOutboundAckRequest,
    MessagingOutboundItem,
    PendingMessageResponse,
    SelectVoiceRequest,
    SpeakRequest,
    SpeakResponse,
    SpotifyClientIdRequest,
    SpotifyLoginResponse,
    SpotifyStatusResponse,
    StatusResponse,
    TelegramAccountResponse,
    TelegramContactRequest,
    TelegramContactResponse,
    TelegramCredentialsRequest,
    TelegramCredentialsStatusResponse,
    TelegramLoginCodeRequest,
    TelegramLoginCodeResponse,
    TelegramLoginPasswordRequest,
    TelegramLoginStartRequest,
    TelegramLoginStartResponse,
    TextQueryRequest,
    TranscribeResponse,
    UIVisibilityRequest,
    VoiceLoopSignalResult,
    VoiceLoopStatus,
    VoiceOptionsResponse,
    VoiceQueryResponse,
    WordPressJobStatusResponse,
    WordPressUploadResponse,
    YouTubeApiKeyRequest,
    YouTubeStatusResponse,
)
from core.secret_store import SecretStoreUnavailableError, delete_secret, get_secret, store_secret
from core.state import state_manager
from core.voice import module_context as voice_module_context
from core.voice import web_pipeline
from modules.ai_bridge import api_providers, provider_auth, virtual_display
from modules.spotify_control import oauth as spotify_oauth
from modules.spotify_control import token_store as spotify_token_store
from modules.youtube_control import service_layer as youtube_service_layer
from modules.ai_bridge.provider_manager import get_provider_manager
from modules.ai_bridge.quota_tracker import quota_tracker
from modules.board_games import announce as board_games_announce
from modules.board_games import service_layer as board_games_service_layer
from modules.board_games import ui_session as board_games_ui_session
from modules.board_games.domain import Difficulty as BoardGameDifficulty
from modules.board_games.domain import GameKind
from modules.code_analysis import service_layer as code_analysis_service_layer
from modules.conversation_log import conversation_log
from modules.delayed_execution import service_layer as delayed_execution_service_layer
from modules.delayed_execution.uow import DelayedExecutionUnitOfWork
from modules.gesture_control import gesture_controller
from modules.gesture_control.overlay_state import overlay_state as gesture_overlay_state
from modules.custom_commands import dispatcher as custom_commands_registry
from modules.custom_commands import service_layer as custom_commands_service_layer
from modules.custom_commands.domain import ActionType
from modules.custom_commands.uow import CustomCommandsUnitOfWork
from modules.figma_control.ws_server import WEBSOCKET_PATH as FIGMA_WEBSOCKET_PATH
from modules.figma_control.ws_server import figma_ws_server
from modules.fitness_tracker import calculations as fitness_calculations
from modules.fitness_tracker import fitness_chat
from modules.fitness_tracker import meal_analyzer as fitness_meal_analyzer
from modules.fitness_tracker import progress_photos as fitness_progress_photos
from modules.fitness_tracker import service_layer as fitness_service_layer
from modules.fitness_tracker.domain import BioProfileSnapshot as FitnessBioProfileSnapshot
from modules.fitness_tracker.domain import BodyMeasurement as FitnessBodyMeasurement
from modules.fitness_tracker.domain import Goal as FitnessGoal
from modules.fitness_tracker.domain import GoalType as FitnessGoalType
from modules.fitness_tracker.domain import MealLogEntry as FitnessMealLogEntry
from modules.image_generation import service_layer as image_generation_service_layer
from modules.image_generation.domain import GeneratedImage
from modules.integrations import packager as integrations_packager
from modules.meeting_recorder import service_layer as meeting_service_layer
from modules.meeting_recorder.domain import Recording as MeetingRecording
from modules.meeting_recorder.domain import RecordingStatus as MeetingRecordingStatus
from modules.meeting_recorder.domain import SummaryStatus as MeetingSummaryStatus
from modules.meeting_recorder.domain import TranscriptStatus as MeetingTranscriptStatus
from modules.meeting_recorder.uow import MeetingRecordingUnitOfWork
from modules.messaging import service_layer as messaging_service_layer
from modules.messaging.uow import MessagingUnitOfWork
from modules.telegram_userbot import client_manager as telegram_client_manager
from modules.telegram_userbot import login as telegram_login
from modules.telegram_userbot import outbound_poller as telegram_outbound_poller
from modules.telegram_userbot import service_layer as telegram_service_layer
from modules.wordpress_bridge import service_layer as wordpress_service_layer

logger = get_logger(__name__)

_composed = compose()
dispatcher = _composed.dispatcher
voice_loop = _composed.voice_loop
reminder_checker = _composed.reminder_checker
hardware_monitor = _composed.hardware_monitor
shutdown_plugin_agent = _composed.shutdown_plugin_agent
recording_processor = _composed.recording_processor
recording_transcriber = _composed.recording_transcriber
messaging_snooze_checker = _composed.messaging_snooze_checker
gmail_poller = _composed.gmail_poller
delayed_command_runner = _composed.delayed_command_runner


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    logger.info("Assistant core service starting up")
    # The conversation transcript is session-scoped, not a permanent
    # history — cleared on every startup so it can't outlive a shutdown
    # (covers a clean power-off and a crash alike). The "Контекст" button
    # in the text-chat panel clears it on demand within a session.
    await asyncio.to_thread(conversation_log.clear)
    if settings.voice_autostart:
        voice_loop.start()
    reminder_checker.start()
    delayed_command_runner.start()
    hardware_monitor.start()
    # Must run before the two pollers start: any row still mid-upload or
    # mid-conversion at this point was orphaned by a previous crash/restart
    # (see modules.meeting_recorder.service_layer.recover_after_restart) and
    # needs to be resolved before the pollers might otherwise pick up a row
    # in an inconsistent state.
    await asyncio.to_thread(meeting_service_layer.recover_after_restart, MeetingRecordingUnitOfWork())
    await asyncio.to_thread(meeting_service_layer.cleanup_orphaned_directories, MeetingRecordingUnitOfWork())
    recording_processor.start()
    recording_transcriber.start()
    messaging_snooze_checker.start()
    # Degrades gracefully: logs and stays idle if no Gmail credentials
    # are configured yet (python -m modules.gmail.login not run).
    gmail_poller.start()
    # Same graceful-degradation idea: connect_account skips (and logs) any
    # account missing app credentials or a valid stored session instead of
    # raising, so a broken/never-configured Telegram setup can't block
    # startup — see modules.telegram_userbot.client_manager.connect_account.
    await telegram_client_manager.connect_all_stored_accounts()
    telegram_outbound_task = asyncio.create_task(telegram_outbound_poller.run_forever())
    yield
    voice_loop.stop()
    reminder_checker.stop()
    delayed_command_runner.stop()
    await asyncio.to_thread(gesture_controller.stop)
    hardware_monitor.stop()
    recording_processor.stop()
    recording_transcriber.stop()
    messaging_snooze_checker.stop()
    gmail_poller.stop()
    telegram_outbound_poller.stop()
    telegram_outbound_task.cancel()
    await get_provider_manager().close_all()
    virtual_display.stop()
    logger.info("Assistant core service shutting down")


app = FastAPI(title="Assistant Core", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    allow_credentials=False,
)

_TOKEN_HEADER = "x-assistant-token"

# Spotify's own redirect after the user approves login lands here directly
# from their browser — it was never our frontend, so it can't carry
# x-assistant-token/?token=. Safe to exempt: the callback's own `state`
# param (see modules/spotify_control/oauth.py's consume_pending_login) is
# itself unforgeable CSRF protection, generated by us moments earlier and
# required to match before anything is done with the `code` that comes
# with it.
_UNAUTHENTICATED_PATHS = {"/api/spotify/callback"}


@app.middleware("http")
async def require_api_token(request: Request, call_next):  # type: ignore[no-untyped-def]
    """bind_host defaults to 0.0.0.0 (see core/config.py's Settings.bind_host),
    so every /api/* route below — including dangerous=True commands like
    ui_action/messaging_reply, gated only by a two-step dispatch+confirm
    that any device on the LAN could otherwise complete itself — must prove
    it knows this machine's api_token first. OPTIONS is always let through
    unauthenticated so CORS preflight (which never carries custom headers)
    keeps working; the static frontend build below isn't under /api/ so the
    page itself always loads, it just can't call anything until the token
    is attached (see frontend/src/api/client.ts). _UNAUTHENTICATED_PATHS is
    a narrow, explicit exception list for the handful of routes (currently
    just Spotify's OAuth callback) that a third party redirects straight to
    and so can never carry our token."""
    if (
        request.method != "OPTIONS"
        and request.url.path.startswith("/api/")
        and request.url.path not in _UNAUTHENTICATED_PATHS
    ):
        header_token = request.headers.get(_TOKEN_HEADER)
        query_token = request.query_params.get("token")
        if settings.api_token not in (header_token, query_token):
            return JSONResponse(status_code=401, content={"detail": "Missing or invalid API token."})
    response: Response = await call_next(request)
    return response


@app.get("/api/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    return StatusResponse(
        state=state_manager.state,
        detail=state_manager.detail,
        active_module_context=voice_module_context.current(),
        gesture_mode_active=gesture_overlay_state.active,
        gesture_cursor_scale=gesture_overlay_state.scale,
    )


@app.get("/api/commands", response_model=list[CommandDescriptor])
async def list_commands() -> list[CommandDescriptor]:
    return dispatcher.list_commands()


@app.get("/api/conversation", response_model=list[ConversationTurnResponse])
async def get_conversation(limit: int = 200) -> list[ConversationTurnResponse]:
    """Merged transcript of spoken and typed turns (see
    modules/conversation_log) so the desktop text-chat panel can show — and
    keep across restarts — what the assistant said out loud during a voice
    conversation, not just what was typed."""
    turns = await asyncio.to_thread(conversation_log.recent, max(1, min(limit, 1000)))
    return [ConversationTurnResponse(**turn.to_dict()) for turn in turns]


@app.post("/api/conversation/clear", response_model=CommandResponse)
async def clear_conversation() -> CommandResponse:
    """Wipes the current session's transcript and the voice loop's one-line
    short-term memory (the "Контекст" button)."""
    await asyncio.to_thread(conversation_log.clear)
    voice_loop.clear_dialog_context()
    return CommandResponse(
        status=CommandStatus.EXECUTED, command="conversation_clear", message="Контекст очищен."
    )


@app.get("/api/gesture/preview")
async def gesture_preview() -> Response:
    """MJPEG stream of the annotated webcam frames — only meaningful while
    gesture mode is active; serves a single placeholder-free 503 otherwise
    so the <img> just shows nothing. See modules/gesture_control."""
    if not gesture_controller.is_active():
        return JSONResponse(status_code=503, content={"detail": "Режим жестов не активен."})

    async def _frames():
        boundary = b"--frame\r\n"
        while gesture_controller.is_active():
            jpeg = gesture_controller.latest_jpeg()
            if jpeg:
                yield boundary + b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            await asyncio.sleep(1 / 15)

    return StreamingResponse(_frames(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.post("/api/gesture/cursor_scale", response_model=CommandResponse)
async def gesture_set_cursor_scale(scale: float) -> CommandResponse:
    applied = await asyncio.to_thread(gesture_controller.set_cursor_scale, scale)
    return CommandResponse(
        status=CommandStatus.EXECUTED,
        command="gesture_cursor_scale",
        message=f"Размер курсора: {round(applied * 100)}%.",
    )


@app.get("/api/delayed", response_model=list[DelayedTaskResponse])
async def list_delayed_tasks() -> list[DelayedTaskResponse]:
    """Pending delayed commands ("открой браузер через 10 минут"), soonest
    first — see modules/delayed_execution."""
    tasks = await asyncio.to_thread(
        delayed_execution_service_layer.list_pending, DelayedExecutionUnitOfWork()
    )
    return [
        DelayedTaskResponse(
            id=task.id,
            original_text=task.original_text,
            command_name=task.command_name,
            run_at=task.run_at.isoformat(),
        )
        for task in tasks
    ]


@app.post("/api/delayed/{task_id}/cancel", response_model=CommandResponse)
async def cancel_delayed_task(task_id: int) -> CommandResponse:
    cancelled = await asyncio.to_thread(
        delayed_execution_service_layer.cancel, DelayedExecutionUnitOfWork(), task_id
    )
    if not cancelled:
        return CommandResponse(
            status=CommandStatus.FAILED,
            command="delayed_cancel",
            message=f"Отложенная задача №{task_id} не найдена или уже выполнена.",
        )
    return CommandResponse(
        status=CommandStatus.EXECUTED,
        command="delayed_cancel",
        message=f"Отложенная задача №{task_id} отменена.",
    )


@app.get("/api/commands/ui", response_model=list[CommandButtonDescriptor])
async def list_command_buttons() -> list[CommandButtonDescriptor]:
    """Curated subset of list_commands() with label/icon/params_schema for
    the frontend's button-panel alternative to voice input (see
    core/command_ui_metadata.py) — commands with no UI metadata (open_app,
    click, type_text, ...) are omitted rather than shown with guessed
    params."""
    buttons: list[CommandButtonDescriptor] = []
    for descriptor in dispatcher.list_commands():
        meta = COMMAND_UI_METADATA.get(descriptor.name)
        if meta is None:
            continue
        params_schema = (
            [CommandParamField(**field.__dict__) for field in meta.params_schema]
            if meta.params_schema
            else None
        )
        buttons.append(
            CommandButtonDescriptor(
                name=descriptor.name,
                label=meta.label,
                icon=meta.icon,
                dangerous=descriptor.dangerous,
                description=descriptor.description,
                group=meta.group,
                params_schema=params_schema,
            )
        )
    return buttons


@app.post("/api/command", response_model=CommandResponse)
async def run_command(request: CommandRequest) -> CommandResponse:
    try:
        return await dispatcher.dispatch(request.command, request.params)
    except UnknownCommandError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown command: {exc}") from exc


@app.post("/api/command/confirm", response_model=CommandResponse)
async def confirm_command(request: ConfirmRequest) -> CommandResponse:
    response = await dispatcher.confirm(request.token, request.approved)
    # The text-chat panel resolves a confirmation_required reply through
    # this route, so the outcome message ("Компьютер выключается", ...) is
    # part of that typed conversation and belongs in the transcript too.
    if response.message:
        await asyncio.to_thread(conversation_log.append, "assistant", response.message, "text")
    return response


@app.websocket(FIGMA_WEBSOCKET_PATH)
async def figma_plugin_socket(websocket: WebSocket) -> None:
    # No require_api_token middleware coverage here — Starlette's
    # @app.middleware("http") only wraps HTTP requests, not WebSocket
    # handshakes — so figma_ws_server.handle_connection does its own token
    # check (see that method's docstring) before accepting the connection.
    await figma_ws_server.handle_connection(websocket)


@app.get("/api/ai_bridge/status", response_model=AIBridgeStatus)
async def get_ai_bridge_status() -> AIBridgeStatus:
    logged_in = await provider_auth.get_logged_in_map()
    return AIBridgeStatus(**get_provider_manager().status(), logged_in=logged_in)


@app.get("/api/ui/visibility_request", response_model=UIVisibilityRequest)
async def get_ui_visibility_request() -> UIVisibilityRequest:
    # Consume semantics: Electron's main process polls this to learn about
    # show_window/hide_window voice commands, since the Python backend has no
    # direct handle to the renderer's BrowserWindow.
    return UIVisibilityRequest(action=state_manager.consume_ui_visibility_request())


@app.get("/api/ui/image_request", response_model=ImageRequest)
async def get_image_request() -> ImageRequest:
    return ImageRequest(svg=state_manager.consume_image_request())


@app.get("/api/voice/status", response_model=VoiceLoopStatus)
async def get_voice_status() -> VoiceLoopStatus:
    return VoiceLoopStatus(running=voice_loop.is_running)


@app.post("/api/voice/start", response_model=VoiceLoopStatus)
async def start_voice() -> VoiceLoopStatus:
    voice_loop.start()
    return VoiceLoopStatus(running=voice_loop.is_running)


@app.post("/api/voice/stop", response_model=VoiceLoopStatus)
async def stop_voice() -> VoiceLoopStatus:
    await asyncio.to_thread(voice_loop.stop)
    return VoiceLoopStatus(running=voice_loop.is_running)


@app.post("/api/voice/trigger", response_model=VoiceLoopSignalResult)
async def trigger_voice() -> VoiceLoopSignalResult:
    """Emulates the wake phrase without it being spoken — the Electron
    "Начать разговор" button drives this same always-on backend loop/mic
    instead of opening a second one in the browser (see
    VoiceAssistantLoop.request_manual_wake). Unlike /api/voice/start, this
    never starts the loop itself; `accepted=False` means it wasn't
    running to receive the trigger."""
    return VoiceLoopSignalResult(accepted=voice_loop.request_manual_wake())


@app.post("/api/voice/pause", response_model=VoiceLoopSignalResult)
async def pause_voice() -> VoiceLoopSignalResult:
    """Emulates the configured stop word — the Electron "Завершить
    разговор" button pauses this same loop the way saying the stop word
    would, instead of the full /api/voice/stop teardown (see
    VoiceAssistantLoop.request_pause)."""
    return VoiceLoopSignalResult(accepted=voice_loop.request_pause())


@app.post("/api/voice/query", response_model=VoiceQueryResponse)
async def voice_query(
    audio: UploadFile = File(...), language: str | None = Form(None)
) -> VoiceQueryResponse:
    """Thin-client voice endpoint: a phone/browser records audio with
    MediaRecorder and posts the blob here. All processing (STT, intent
    resolution, command dispatch, TTS) runs on this machine — see
    core/voice/web_pipeline.py — the client only records and plays back.

    `language`, if the client sends it (from a UI language toggle), pins
    Whisper decoding to that language instead of relying on autodetect."""
    data = await audio.read()
    try:
        result = await web_pipeline.process_voice_query(
            dispatcher, data, audio.filename or "audio.webm", language
        )
    except web_pipeline.InvalidAudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logger.exception("Unhandled error processing /api/voice/query")
        raise HTTPException(
            status_code=500, detail="Internal error while processing the voice query."
        ) from None
    return result


@app.post("/api/voice/transcribe", response_model=TranscribeResponse)
async def voice_transcribe(
    audio: UploadFile = File(...), language: str | None = Form(None)
) -> TranscribeResponse:
    """Transcription only — no intent resolution or command dispatch, unlike
    /api/voice/query above. For one-shot mic-to-field voice input (see
    frontend/src/hooks/useOneShotVoiceInput.ts): dictating an instruction
    into a text field must never risk running it as a command."""
    data = await audio.read()
    try:
        text = await web_pipeline.transcribe_uploaded_audio(data, audio.filename or "audio.webm", language)
    except web_pipeline.InvalidAudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logger.exception("Unhandled error processing /api/voice/transcribe")
        raise HTTPException(status_code=500, detail="Internal error while transcribing audio.") from None
    return TranscribeResponse(text=text)


_WORDPRESS_UPLOAD_DIR = DATA_DIR / "wordpress_uploads"


@app.post("/api/wordpress/upload", response_model=WordPressUploadResponse)
async def wordpress_upload(
    site_url: str = Form(...),
    rewrite_with_ai: bool = Form(False),
    files: list[UploadFile] = File(...),
) -> WordPressUploadResponse:
    """Called directly from JavaScript running in wp-admin (see
    wordpress-plugin/) — the browser making the request is on the user's own
    LAN, same as the thin voice client (see LanQrPanel.tsx/detect_lan_ip),
    so this doesn't need the WordPress server itself to reach out to the
    backend. Kicks off content_processor -> wp_draft_publisher as a
    background task and returns a job_id immediately; the plugin polls
    GET /api/wordpress/upload/{job_id} for the result."""
    job = wordpress_service_layer.create_job(site_url)
    job_dir = _WORDPRESS_UPLOAD_DIR / job.job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[str] = []
    for upload in files:
        destination = job_dir / (upload.filename or "upload")
        data = await upload.read()
        destination.write_bytes(data)
        saved_paths.append(str(destination))

    asyncio.create_task(wordpress_service_layer.run_upload_job(job.job_id, saved_paths, rewrite_with_ai=rewrite_with_ai))
    return WordPressUploadResponse(job_id=job.job_id)


@app.get("/api/wordpress/upload/{job_id}", response_model=WordPressJobStatusResponse)
async def wordpress_upload_status(job_id: str) -> WordPressJobStatusResponse:
    job = wordpress_service_layer.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job: {job_id}")
    return WordPressJobStatusResponse(
        job_id=job.job_id, status=job.status.value, message=job.message, edit_url=job.edit_url
    )
    return VoiceQueryResponse(
        transcribed_text=result.transcribed_text,
        reply_text=result.reply_text,
        language=result.language,
        audio_wav_base64=result.audio_wav_base64,
        status=result.status,
        token=result.token,
    )


def _custom_command_to_response(command: Any) -> CustomCommandResponse:
    return CustomCommandResponse(
        id=command.id,
        trigger_phrase=command.trigger_phrase,
        action_type=command.action_type.value,
        action_payload=command.action_payload,
        created_at=command.created_at.isoformat() if command.created_at else "",
    )


@app.get("/api/custom_commands", response_model=CustomCommandListResponse)
async def list_custom_commands() -> CustomCommandListResponse:
    commands = custom_commands_service_layer.get_all_commands(CustomCommandsUnitOfWork())
    return CustomCommandListResponse(commands=[_custom_command_to_response(c) for c in commands])


@app.post("/api/custom_commands", response_model=CustomCommandResponse)
async def create_or_update_custom_command(
    trigger_phrase: str = Form(...),
    action_type: str = Form(...),
    command_id: str | None = Form(None),
    url: str | None = Form(None),
    executable_path: str | None = Form(None),
    instruction: str | None = Form(None),
    media_type: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> CustomCommandResponse:
    """Create (command_id omitted) or update (command_id set) a custom
    command — see modules/custom_commands/. A single multipart route
    handles every action_type (rather than one JSON route + one upload
    route) since the frontend's create/edit form is one component either
    way and only two of the five action types actually attach a file — see
    modules/custom_commands/service_layer.py's create_command/
    update_command for where the file is actually copied under
    DATA_DIR/custom_commands/attachments/{command_id}/ (never the
    version-controlled modules/custom_commands/ tree)."""
    try:
        parsed_type = ActionType(action_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown action_type: {action_type}") from None

    payload: dict[str, Any] = {}
    if parsed_type is ActionType.OPEN_LINK:
        if not url:
            raise HTTPException(status_code=400, detail="url is required for open_link")
        payload["url"] = url
    elif parsed_type is ActionType.LAUNCH_APP:
        if not executable_path:
            raise HTTPException(status_code=400, detail="executable_path is required for launch_app")
        payload["executable_path"] = executable_path
    elif parsed_type is ActionType.TEXT_INSTRUCTION:
        if not instruction:
            raise HTTPException(status_code=400, detail="instruction is required for text_instruction")
        payload["instruction"] = instruction
    elif parsed_type in (ActionType.PLAY_AUDIO, ActionType.OPEN_MEDIA):
        if parsed_type is ActionType.OPEN_MEDIA:
            if media_type not in ("photo", "video"):
                raise HTTPException(status_code=400, detail="media_type must be 'photo' or 'video'")
            payload["media_type"] = media_type
        if file is None:
            # Editing an existing command's trigger phrase/type without
            # re-attaching a file — keep the file it already has instead of
            # silently dropping it.
            existing = command_id and custom_commands_service_layer.get_command(
                CustomCommandsUnitOfWork(), command_id
            )
            if not existing or "file_path" not in existing.action_payload:
                raise HTTPException(status_code=400, detail="file is required")
            payload["file_path"] = existing.action_payload["file_path"]

    attachment: tuple[str, bytes] | None = None
    if file is not None:
        attachment = (file.filename or "attachment", await file.read())

    uow = CustomCommandsUnitOfWork()
    if command_id:
        command = custom_commands_service_layer.update_command(
            uow, command_id, trigger_phrase, parsed_type, payload, attachment=attachment
        )
        if command is None:
            raise HTTPException(status_code=404, detail=f"Unknown custom command: {command_id}")
    else:
        command = custom_commands_service_layer.create_command(
            uow, trigger_phrase, parsed_type, payload, attachment=attachment
        )

    custom_commands_registry.refresh()
    return _custom_command_to_response(command)


@app.delete("/api/custom_commands/{command_id}")
async def delete_custom_command(command_id: str) -> dict[str, bool]:
    removed = custom_commands_service_layer.delete_command(CustomCommandsUnitOfWork(), command_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Unknown custom command: {command_id}")
    custom_commands_registry.refresh()
    return {"removed": True}


def _board_game_state_response(
    session: Any,
    *,
    last_player_move: str | None = None,
    last_engine_move: str | None = None,
    last_engine_move_from: str | None = None,
    last_engine_move_to: str | None = None,
    mistake_message: str | None = None,
) -> BoardGameStateResponse:
    is_over = board_games_service_layer.is_over(session)
    legal_move_squares = (
        []
        if is_over
        else [
            LegalMoveSquares(from_square=from_sq, to_square=to_sq, label=label)
            for from_sq, to_sq, label in board_games_service_layer.legal_moves_with_squares(session)
        ]
    )
    return BoardGameStateResponse(
        kind=session.kind.value,
        difficulty=session.difficulty.value if session.difficulty else None,
        board_svg=board_games_service_layer.render_svg(session),
        legal_moves=[] if is_over else board_games_service_layer.legal_move_labels(session),
        legal_move_squares=legal_move_squares,
        is_over=is_over,
        is_check=board_games_service_layer.is_check(session),
        result=board_games_service_layer.result_string(session) if is_over else None,
        last_player_move=last_player_move,
        last_engine_move=last_engine_move,
        last_engine_move_from=last_engine_move_from,
        last_engine_move_to=last_engine_move_to,
        mistake_message=mistake_message,
    )


def _parse_board_game_kind(raw: str) -> GameKind:
    try:
        return GameKind(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown game kind: {raw}") from None


def _parse_board_game_difficulty(raw: str | None) -> BoardGameDifficulty | None:
    if raw is None:
        return None
    try:
        return BoardGameDifficulty(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown difficulty: {raw}") from None


@app.post("/api/boardgames/start", response_model=BoardGameStateResponse)
async def start_board_game(request: BoardGameStartRequest) -> BoardGameStateResponse:
    kind = _parse_board_game_kind(request.kind)
    difficulty = _parse_board_game_difficulty(request.difficulty)
    session = await asyncio.to_thread(board_games_ui_session.start, kind, difficulty)
    return _board_game_state_response(session)


@app.get("/api/boardgames/current", response_model=BoardGameStateResponse | None)
async def get_current_board_game() -> BoardGameStateResponse | None:
    session = board_games_ui_session.current()
    if session is None:
        return None
    return _board_game_state_response(session)


@app.post("/api/boardgames/move", response_model=BoardGameStateResponse)
async def play_board_game_move(request: BoardGameMoveRequest) -> BoardGameStateResponse:
    try:
        session = board_games_ui_session.require_current()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    legal = board_games_service_layer.legal_move_labels(session)
    if request.notation not in legal:
        raise HTTPException(status_code=400, detail=f"Illegal move: {request.notation}")

    judgement = await asyncio.to_thread(board_games_service_layer.apply_player_move, session, request.notation)
    mistake_message = board_games_announce.mistake_text(judgement) if judgement.was_mistake else None

    if board_games_service_layer.is_over(session):
        return _board_game_state_response(session, last_player_move=request.notation, mistake_message=mistake_message)

    # A real engine search takes long enough at higher difficulties to feel
    # like "thinking" on its own, but the easy tiers return near-instantly —
    # the reply then lands in the same network round-trip as the player's
    # own move, reading as "the board just teleported" rather than a turn
    # being taken. A small fixed pause makes every difficulty feel like an
    # opponent moved, not a bug.
    await asyncio.sleep(0.6)
    engine_move = await asyncio.to_thread(board_games_service_layer.apply_engine_move, session)
    return _board_game_state_response(
        session,
        last_player_move=request.notation,
        last_engine_move=engine_move.notation,
        last_engine_move_from=engine_move.from_square,
        last_engine_move_to=engine_move.to_square,
        mistake_message=mistake_message,
    )


@app.post("/api/boardgames/finish")
async def finish_board_game() -> dict[str, str]:
    summary = await asyncio.to_thread(board_games_ui_session.finish)
    if summary is None:
        return {"message": "Игра не была начата."}
    return {"message": board_games_announce.result_text(summary.result_string)}


@app.post("/api/voice/confirm", response_model=VoiceQueryResponse)
async def voice_confirm(
    audio: UploadFile = File(...), token: str = Form(...), language: str | None = Form(None)
) -> VoiceQueryResponse:
    """Voice counterpart of POST /api/command/confirm: the thin-client
    conversation loop records the user's spoken yes/no answer to a
    confirmation_required reply and posts it here (with that reply's token)
    instead of to /api/voice/query, which would otherwise try to interpret a
    bare "да" as a brand new command and fail to understand it — see
    core/voice/web_pipeline.py.process_voice_confirmation."""
    data = await audio.read()
    try:
        result = await web_pipeline.process_voice_confirmation(
            dispatcher, data, audio.filename or "audio.webm", token, language
        )
    except web_pipeline.InvalidAudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logger.exception("Unhandled error processing /api/voice/confirm")
        raise HTTPException(
            status_code=500, detail="Internal error while processing the voice confirmation."
        ) from None
    return VoiceQueryResponse(
        transcribed_text=result.transcribed_text,
        reply_text=result.reply_text,
        language=result.language,
        audio_wav_base64=result.audio_wav_base64,
        status=result.status,
        token=result.token,
    )


@app.post("/api/voice/text_query", response_model=VoiceQueryResponse)
async def text_query(request: TextQueryRequest) -> VoiceQueryResponse:
    """Keyboard counterpart of /api/voice/query for the desktop UI's typed
    text input: same interpret/dispatch pipeline, no microphone or speech
    synthesis involved — see core/voice/web_pipeline.py.process_text_query."""
    try:
        result = await web_pipeline.process_text_query(dispatcher, request.text, request.language)
    except Exception:
        logger.exception("Unhandled error processing /api/voice/text_query")
        raise HTTPException(
            status_code=500, detail="Internal error while processing the text query."
        ) from None
    return VoiceQueryResponse(
        transcribed_text=result.transcribed_text,
        reply_text=result.reply_text,
        language=result.language,
        audio_wav_base64=result.audio_wav_base64,
        status=result.status,
        token=result.token,
    )


@app.post("/api/voice/speak", response_model=SpeakResponse)
async def voice_speak(request: SpeakRequest) -> SpeakResponse:
    """Synthesizes arbitrary text to speech, e.g. so a phone client can hear
    the result of a confirm/cancel action taken via POST /api/command/confirm
    (which itself returns text only), or to preview a voice (request.speaker)
    without changing the persisted default."""
    audio_b64 = await asyncio.to_thread(
        web_pipeline.synthesize_speech, request.text, request.language, request.speaker
    )
    return SpeakResponse(audio_wav_base64=audio_b64)


@app.get("/api/voice/voices", response_model=VoiceOptionsResponse)
async def get_voice_options() -> VoiceOptionsResponse:
    voices, selected = web_pipeline.list_voices()
    return VoiceOptionsResponse(voices=voices, selected=selected)


@app.post("/api/voice/voices/select", response_model=VoiceOptionsResponse)
async def select_voice_option(request: SelectVoiceRequest) -> VoiceOptionsResponse:
    try:
        web_pipeline.select_voice(request.speaker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    voices, selected = web_pipeline.list_voices()
    return VoiceOptionsResponse(voices=voices, selected=selected)


@app.get("/api/lan_url", response_model=LanUrlResponse)
async def get_lan_url() -> LanUrlResponse:
    """The address a phone on the same Wi-Fi/LAN should open to use this
    machine as a thin client (see the QR code panel in the desktop UI).
    Carries ?token= so the page that loads from it can bootstrap
    frontend/src/api/client.ts's auth header from the URL — see
    require_api_token above; scanning the QR code is what "pairs" the
    phone, nothing else transfers the token to it."""
    return LanUrlResponse(url=f"http://{detect_lan_ip()}:{settings.port}/?token={settings.api_token}")


@app.get("/api/integrations/wordpress/plugin.zip")
async def download_wordpress_plugin() -> Response:
    """One-click alternative to IntegrationsPanel's manual "copy the folder,
    fill in the address and token yourself" instructions — the zip already
    has both filled in as this plugin's settings-screen defaults, so
    uploading it via WordPress's own Plugins → Add New → Upload Plugin is
    the only step left."""
    data = await asyncio.to_thread(integrations_packager.build_wordpress_plugin_zip)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=jarvis-wordpress-plugin.zip"},
    )


@app.get("/api/integrations/figma/plugin.zip")
async def download_figma_plugin() -> Response:
    """Same one-click idea as the WordPress download above — WS_TOKEN is
    already filled in and code.js already built, so "Import plugin from
    manifest…" in Figma Desktop is the only step left."""
    try:
        data = await asyncio.to_thread(integrations_packager.build_figma_plugin_zip)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=jarvis-figma-plugin.zip"},
    )


@app.get("/api/integrations/blender/addon.zip")
async def download_blender_addon() -> Response:
    """Same one-click idea as the WordPress/Figma downloads above — already
    zipped as the single top-level folder Blender's own Install… expects,
    so the user no longer has to zip it themselves."""
    data = await asyncio.to_thread(integrations_packager.build_blender_addon_zip)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=jarvis-blender-addon.zip"},
    )


def _youtube_status_response() -> YouTubeStatusResponse:
    quota = youtube_service_layer.quota_status()
    return YouTubeStatusResponse(
        key_configured=get_secret(youtube_service_layer.API_KEY_SECRET_NAME) is not None,
        units_used=quota.units_used,
        daily_limit=quota.daily_limit,
        remaining_searches=quota.remaining_searches,
        near_limit=quota.near_limit,
        exhausted=quota.exhausted,
    )


@app.get("/api/youtube/status", response_model=YouTubeStatusResponse)
async def get_youtube_status() -> YouTubeStatusResponse:
    return _youtube_status_response()


@app.post("/api/youtube/api_key", response_model=YouTubeStatusResponse)
async def save_youtube_api_key(request: YouTubeApiKeyRequest) -> YouTubeStatusResponse:
    try:
        store_secret(youtube_service_layer.API_KEY_SECRET_NAME, request.api_key)
    except SecretStoreUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _youtube_status_response()


@app.delete("/api/youtube/api_key", response_model=YouTubeStatusResponse)
async def delete_youtube_api_key() -> YouTubeStatusResponse:
    try:
        delete_secret(youtube_service_layer.API_KEY_SECRET_NAME)
    except SecretStoreUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _youtube_status_response()


def _gemini_key_status_response() -> GeminiKeyStatusResponse:
    return GeminiKeyStatusResponse(
        key_configured=get_secret(api_providers.GEMINI_API_KEY_SECRET_NAME) is not None,
        requests_used_today=quota_tracker.daily_count(api_providers.GeminiApiAdapter.name),
        daily_limit=api_providers.GEMINI_RPD_LIMIT,
    )


@app.get("/api/ai_bridge/gemini_api_key", response_model=GeminiKeyStatusResponse)
async def get_gemini_key_status() -> GeminiKeyStatusResponse:
    return _gemini_key_status_response()


@app.post("/api/ai_bridge/gemini_api_key", response_model=GeminiKeyStatusResponse)
async def save_gemini_api_key(request: ApiKeyRequest) -> GeminiKeyStatusResponse:
    try:
        store_secret(api_providers.GEMINI_API_KEY_SECRET_NAME, request.api_key)
    except SecretStoreUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _gemini_key_status_response()


@app.delete("/api/ai_bridge/gemini_api_key", response_model=GeminiKeyStatusResponse)
async def delete_gemini_api_key() -> GeminiKeyStatusResponse:
    try:
        delete_secret(api_providers.GEMINI_API_KEY_SECRET_NAME)
    except SecretStoreUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _gemini_key_status_response()


def _claude_key_status_response() -> ClaudeKeyStatusResponse:
    return ClaudeKeyStatusResponse(
        key_configured=get_secret(api_providers.CLAUDE_API_KEY_SECRET_NAME) is not None
    )


@app.get("/api/ai_bridge/claude_api_key", response_model=ClaudeKeyStatusResponse)
async def get_claude_key_status() -> ClaudeKeyStatusResponse:
    return _claude_key_status_response()


@app.post("/api/ai_bridge/claude_api_key", response_model=ClaudeKeyStatusResponse)
async def save_claude_api_key(request: ApiKeyRequest) -> ClaudeKeyStatusResponse:
    try:
        store_secret(api_providers.CLAUDE_API_KEY_SECRET_NAME, request.api_key)
    except SecretStoreUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _claude_key_status_response()


@app.delete("/api/ai_bridge/claude_api_key", response_model=ClaudeKeyStatusResponse)
async def delete_claude_api_key() -> ClaudeKeyStatusResponse:
    try:
        delete_secret(api_providers.CLAUDE_API_KEY_SECRET_NAME)
    except SecretStoreUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _claude_key_status_response()


def _spotify_status_response() -> SpotifyStatusResponse:
    return SpotifyStatusResponse(
        client_id_configured=spotify_token_store.get_client_id() is not None,
        connected=spotify_token_store.is_connected(),
        redirect_uri=spotify_oauth.redirect_uri(),
    )


@app.get("/api/spotify/status", response_model=SpotifyStatusResponse)
async def get_spotify_status() -> SpotifyStatusResponse:
    return _spotify_status_response()


@app.post("/api/spotify/client_id", response_model=SpotifyStatusResponse)
async def save_spotify_client_id(request: SpotifyClientIdRequest) -> SpotifyStatusResponse:
    try:
        spotify_token_store.store_client_id(request.client_id)
    except SecretStoreUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _spotify_status_response()


@app.post("/api/spotify/login", response_model=SpotifyLoginResponse)
async def start_spotify_login() -> SpotifyLoginResponse:
    client_id = spotify_token_store.get_client_id()
    if not client_id:
        raise HTTPException(status_code=400, detail="Сначала укажите Spotify Client ID.")
    return SpotifyLoginResponse(authorize_url=spotify_oauth.start_login(client_id))


@app.delete("/api/spotify/connection", response_model=SpotifyStatusResponse)
async def disconnect_spotify() -> SpotifyStatusResponse:
    try:
        spotify_token_store.disconnect()
    except SecretStoreUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _spotify_status_response()


@app.get("/api/spotify/callback")
async def spotify_oauth_callback(request: Request) -> HTMLResponse:
    error = request.query_params.get("error")
    if error:
        return HTMLResponse(f"<p>Spotify отказал в авторизации: {error}. Можно закрыть эту вкладку.</p>")

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        return HTMLResponse("<p>Некорректный ответ от Spotify. Можно закрыть эту вкладку.</p>", status_code=400)

    code_verifier = spotify_oauth.consume_pending_login(state)
    if code_verifier is None:
        return HTMLResponse(
            "<p>Эта ссылка авторизации устарела или уже была использована. "
            "Вернитесь в настройки и нажмите «Войти» ещё раз.</p>",
            status_code=400,
        )

    client_id = spotify_token_store.get_client_id()
    if not client_id:
        return HTMLResponse("<p>Spotify Client ID не найден. Можно закрыть эту вкладку.</p>", status_code=400)

    try:
        payload = await spotify_oauth.exchange_code(code, code_verifier, client_id)
    except spotify_oauth.SpotifyOAuthError as exc:
        logger.exception("Spotify OAuth code exchange failed")
        return HTMLResponse(f"<p>Не удалось завершить авторизацию: {exc}. Можно закрыть эту вкладку.</p>")

    spotify_token_store.store_refresh_token(payload["refresh_token"])
    return HTMLResponse("<p>Spotify подключён. Можно закрыть эту вкладку и вернуться в NABVE.</p>")


def _generated_image_response(image: GeneratedImage) -> GeneratedImageResponse:
    assert image.id is not None
    assert image.created_at is not None
    return GeneratedImageResponse(
        id=image.id, prompt=image.prompt, source=image.source, created_at=image.created_at.isoformat()
    )


@app.get("/api/images", response_model=list[GeneratedImageResponse])
async def list_generated_images() -> list[GeneratedImageResponse]:
    images = await asyncio.to_thread(image_generation_service_layer.list_images)
    return [_generated_image_response(image) for image in images]


@app.get("/api/images/{image_id}/file")
async def get_generated_image_file(image_id: int) -> FileResponse:
    image = await asyncio.to_thread(image_generation_service_layer.get_image, image_id)
    if image is None or not image.image_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(image.image_path, media_type="image/png")


@app.delete("/api/images/{image_id}")
async def delete_generated_image(image_id: int) -> dict[str, bool]:
    deleted = await asyncio.to_thread(image_generation_service_layer.delete_image, image_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"deleted": True}


def _github_status_response() -> GithubStatusResponse:
    return GithubStatusResponse(
        pat_configured=get_secret(code_analysis_service_layer.GITHUB_PAT_SECRET_NAME) is not None
    )


@app.get("/api/integrations/github_pat", response_model=GithubStatusResponse)
async def get_github_pat_status() -> GithubStatusResponse:
    return _github_status_response()


@app.post("/api/integrations/github_pat", response_model=GithubStatusResponse)
async def save_github_pat(request: GithubPatRequest) -> GithubStatusResponse:
    try:
        store_secret(code_analysis_service_layer.GITHUB_PAT_SECRET_NAME, request.pat)
    except SecretStoreUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _github_status_response()


@app.delete("/api/integrations/github_pat", response_model=GithubStatusResponse)
async def delete_github_pat() -> GithubStatusResponse:
    try:
        delete_secret(code_analysis_service_layer.GITHUB_PAT_SECRET_NAME)
    except SecretStoreUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _github_status_response()


def _telegram_account_response(account) -> TelegramAccountResponse:  # noqa: ANN001
    assert account.id is not None
    return TelegramAccountResponse(
        id=account.id,
        label=account.label,
        phone_number=account.phone_number,
        connected=telegram_service_layer.is_account_connected(account.id),
    )


@app.get("/api/telegram/credentials", response_model=TelegramCredentialsStatusResponse)
async def get_telegram_credentials_status() -> TelegramCredentialsStatusResponse:
    return TelegramCredentialsStatusResponse(configured=telegram_login.get_app_credentials() is not None)


@app.post("/api/telegram/credentials", response_model=TelegramCredentialsStatusResponse)
async def save_telegram_credentials(request: TelegramCredentialsRequest) -> TelegramCredentialsStatusResponse:
    try:
        telegram_login.store_app_credentials(request.api_id, request.api_hash)
    except SecretStoreUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return TelegramCredentialsStatusResponse(configured=True)


@app.get("/api/telegram/accounts", response_model=list[TelegramAccountResponse])
async def list_telegram_accounts() -> list[TelegramAccountResponse]:
    accounts = await asyncio.to_thread(telegram_service_layer.list_accounts)
    return [_telegram_account_response(a) for a in accounts]


@app.delete("/api/telegram/accounts/{account_id}")
async def delete_telegram_account(account_id: int) -> dict[str, bool]:
    removed = await telegram_service_layer.remove_account(account_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"deleted": True}


@app.post("/api/telegram/accounts/login/start", response_model=TelegramLoginStartResponse)
async def start_telegram_login(request: TelegramLoginStartRequest) -> TelegramLoginStartResponse:
    try:
        token = await telegram_service_layer.start_account_login(request.label, request.phone_number)
    except (telegram_service_layer.TelegramAccountLimitError, telegram_login.TelegramLoginError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TelegramLoginStartResponse(token=token)


@app.post("/api/telegram/accounts/login/code", response_model=TelegramLoginCodeResponse)
async def submit_telegram_login_code(request: TelegramLoginCodeRequest) -> TelegramLoginCodeResponse:
    try:
        needs_password, account = await telegram_service_layer.submit_login_code(request.token, request.code)
    except telegram_login.TelegramLoginError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TelegramLoginCodeResponse(
        needs_password=needs_password,
        account=_telegram_account_response(account) if account is not None else None,
    )


@app.post("/api/telegram/accounts/login/password", response_model=TelegramAccountResponse)
async def submit_telegram_login_password(request: TelegramLoginPasswordRequest) -> TelegramAccountResponse:
    try:
        account = await telegram_service_layer.submit_login_password(request.token, request.password)
    except telegram_login.TelegramLoginError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _telegram_account_response(account)


@app.get("/api/telegram/contacts", response_model=list[TelegramContactResponse])
async def list_telegram_contacts() -> list[TelegramContactResponse]:
    contacts = await asyncio.to_thread(telegram_service_layer.list_watched_contacts)
    return [TelegramContactResponse(id=c.id, identifier=c.identifier, note=c.note) for c in contacts if c.id]


@app.post("/api/telegram/contacts", response_model=TelegramContactResponse)
async def add_telegram_contact(request: TelegramContactRequest) -> TelegramContactResponse:
    try:
        contact_id = await asyncio.to_thread(
            telegram_service_layer.add_watched_contact, request.identifier, request.note
        )
    except telegram_service_layer.WatchedContactLimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TelegramContactResponse(id=contact_id, identifier=request.identifier, note=request.note)


@app.delete("/api/telegram/contacts/{contact_id}")
async def delete_telegram_contact(contact_id: int) -> dict[str, bool]:
    removed = await asyncio.to_thread(
        messaging_service_layer.remove_watched_contact, MessagingUnitOfWork(), contact_id
    )
    if not removed:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"deleted": True}


@app.get("/api/messaging/pending", response_model=list[PendingMessageResponse])
async def list_pending_messages() -> list[PendingMessageResponse]:
    """Frontend-facing (unlike /api/messaging/incoming and
    /api/messaging/outbound/*, which are the external-bridge contract from
    modules/messaging/BRIDGE.md) — polled by the Settings UI's pending-
    messages toast."""
    pending = await asyncio.to_thread(messaging_service_layer.list_pending, MessagingUnitOfWork())
    return [
        PendingMessageResponse(
            id=m.id, source=m.source, sender_label=m.sender_label, text=m.text,
            received_at=m.received_at.isoformat() if m.received_at else "",
        )
        for m in pending
        if m.id is not None
    ]


def _meeting_recording_response(recording: MeetingRecording) -> MeetingRecordingResponse:
    assert recording.id is not None
    assert recording.created_at is not None
    return MeetingRecordingResponse(
        id=recording.id,
        created_at=recording.created_at.isoformat(),
        status=recording.status.value,
        error=recording.error,
        duration_seconds=recording.duration_seconds,
        size_bytes=recording.size_bytes,
        mic_only=recording.mic_only,
        context_label=recording.context_label,
        transcript_status=recording.transcript_status.value,
        transcript_progress=recording.transcript_progress,
        transcript_error=recording.transcript_error,
        summary_status=recording.summary_status.value,
        summary_error=recording.summary_error,
    )


@app.post("/api/meetings/recordings", response_model=MeetingRecordingCreateResponse)
async def create_meeting_recording(
    request: MeetingRecordingCreateRequest,
) -> MeetingRecordingCreateResponse:
    """Starts a new meeting recording: allocates a row + storage directory
    and returns its id, which the client then streams audio chunks to via
    POST .../chunk. Does not accept audio itself — see that endpoint."""
    recording = await asyncio.to_thread(
        meeting_service_layer.create_recording, MeetingRecordingUnitOfWork(), request.context_label
    )
    assert recording.id is not None
    return MeetingRecordingCreateResponse(id=recording.id)


@app.post("/api/meetings/recordings/{recording_id}/chunk", response_model=MeetingRecordingChunkResponse)
async def append_meeting_recording_chunk(
    recording_id: int, request: Request
) -> MeetingRecordingChunkResponse:
    """Appends one raw audio chunk (the request body, sent as
    application/octet-stream — MediaRecorder's periodic `ondataavailable`
    blob, not a JSON envelope) to the recording's raw file. Streaming
    upload: the client is expected to call this repeatedly through a single
    recording rather than sending the whole file at once."""
    buffer = bytearray()
    async for part in request.stream():
        buffer += part
        if len(buffer) > settings.meeting_recording_max_size_bytes:
            # Aborted while still reading the body in, rather than via
            # request.body() buffering an arbitrarily large single request
            # fully into memory first before any size check ever ran. The
            # real cumulative-across-chunks total is re-checked properly
            # against the DB in append_chunk below — this is just a sanity
            # ceiling on any one request body, using the same overall limit
            # since no legitimate ~5s MediaRecorder chunk would ever
            # approach it.
            raise HTTPException(status_code=413, detail="Uploaded chunk is too large.")
    data = bytes(buffer)
    try:
        size_bytes = await asyncio.to_thread(
            meeting_service_layer.append_chunk, MeetingRecordingUnitOfWork(), recording_id, data
        )
    except meeting_service_layer.RecordingSizeLimitExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MeetingRecordingChunkResponse(size_bytes=size_bytes)


@app.post("/api/meetings/recordings/{recording_id}/finish", response_model=MeetingRecordingResponse)
async def finish_meeting_recording(
    recording_id: int, request: MeetingRecordingFinishRequest
) -> MeetingRecordingResponse:
    """Signals the end of streaming for this recording and hands it off to
    the background processor (conversion + independent duration/size
    validation — see modules.meeting_recorder.processor)."""
    try:
        recording = await asyncio.to_thread(
            meeting_service_layer.finish_recording,
            MeetingRecordingUnitOfWork(),
            recording_id,
            request.mic_only,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _meeting_recording_response(recording)


@app.get("/api/meetings/recordings", response_model=list[MeetingRecordingResponse])
async def list_meeting_recordings() -> list[MeetingRecordingResponse]:
    recordings = await asyncio.to_thread(
        meeting_service_layer.list_recordings, MeetingRecordingUnitOfWork()
    )
    return [_meeting_recording_response(recording) for recording in recordings]


@app.get("/api/meetings/recordings/{recording_id}", response_model=MeetingRecordingResponse)
async def get_meeting_recording(recording_id: int) -> MeetingRecordingResponse:
    """Polled by the client while a recording is PROCESSING/transcribing to
    learn about progress/completion/errors on both background phases."""
    recording = await asyncio.to_thread(
        meeting_service_layer.get_recording, MeetingRecordingUnitOfWork(), recording_id
    )
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    return _meeting_recording_response(recording)


@app.get("/api/meetings/recordings/{recording_id}/audio")
async def get_meeting_recording_audio(recording_id: int) -> FileResponse:
    recording = await asyncio.to_thread(
        meeting_service_layer.get_recording, MeetingRecordingUnitOfWork(), recording_id
    )
    # Gating on status, not just file existence: during PROCESSING,
    # audio.ogg can already exist on disk mid-write (ffmpeg writes its
    # output progressively) — serving it before status flips to READY would
    # hand out a truncated, unplayable file.
    if (
        recording is None
        or recording.status != MeetingRecordingStatus.READY
        or not recording.audio_path.is_file()
    ):
        raise HTTPException(status_code=404, detail="Recording audio not available")
    return FileResponse(recording.audio_path, media_type="audio/ogg")


@app.get("/api/meetings/recordings/{recording_id}/transcript", response_model=MeetingTranscriptResponse)
async def get_meeting_recording_transcript(recording_id: int) -> MeetingTranscriptResponse:
    recording = await asyncio.to_thread(
        meeting_service_layer.get_recording, MeetingRecordingUnitOfWork(), recording_id
    )
    if recording is None or recording.transcript_status != MeetingTranscriptStatus.DONE:
        raise HTTPException(status_code=404, detail="Transcript not available")
    text = await asyncio.to_thread(recording.transcript_path.read_text, "utf-8")
    return MeetingTranscriptResponse(text=text)


@app.get("/api/meetings/recordings/{recording_id}/summary", response_model=MeetingSummaryResponse)
async def get_meeting_recording_summary(recording_id: int) -> MeetingSummaryResponse:
    recording = await asyncio.to_thread(
        meeting_service_layer.get_recording, MeetingRecordingUnitOfWork(), recording_id
    )
    if recording is None or recording.summary_status != MeetingSummaryStatus.DONE:
        raise HTTPException(status_code=404, detail="Summary not available")
    text = await asyncio.to_thread(recording.summary_path.read_text, "utf-8")
    return MeetingSummaryResponse(text=text)


@app.delete("/api/meetings/recordings/{recording_id}", response_model=MeetingRecordingDeleteResponse)
async def delete_meeting_recording(recording_id: int) -> MeetingRecordingDeleteResponse:
    """If the recording's background job (processor or
    transcriber/summarizer) is still running, the delete is flagged rather
    than performed immediately (`pending=True`) — see
    modules.meeting_recorder.service_layer.request_delete for the race this
    avoids."""
    deleted, pending = await asyncio.to_thread(
        meeting_service_layer.request_delete, MeetingRecordingUnitOfWork(), recording_id
    )
    if not deleted and not pending:
        raise HTTPException(status_code=404, detail="Recording not found")
    return MeetingRecordingDeleteResponse(deleted=deleted, pending=pending)


@app.post("/api/messaging/incoming", response_model=MessagingIncomingResponse)
async def receive_messaging_incoming(request: MessagingIncomingRequest) -> MessagingIncomingResponse:
    """Called by an external delivery process (e.g. a separate Telegram bot
    project — see modules/messaging/BRIDGE.md) to hand off one inbound
    message. NABVE1 has no client of its own for any messaging source; this
    is the only way a message ever enters modules.messaging."""
    pending = await asyncio.to_thread(
        messaging_service_layer.record_incoming_message,
        MessagingUnitOfWork(),
        request.source,
        request.sender_identifier,
        request.sender_label,
        request.text,
    )
    if pending is None:
        return MessagingIncomingResponse(recorded=False)
    await messaging_service_layer.notify_new_message(message_bus, pending)
    assert pending.id is not None
    return MessagingIncomingResponse(recorded=True, message_id=pending.id)


@app.get("/api/messaging/outbound/pending", response_model=list[MessagingOutboundItem])
async def list_messaging_outbound_pending() -> list[MessagingOutboundItem]:
    """Polled by the external delivery process to find replies waiting to
    be sent — see modules/messaging/BRIDGE.md."""
    pending = await asyncio.to_thread(messaging_service_layer.list_pending_outbound, MessagingUnitOfWork())
    return [
        MessagingOutboundItem(
            id=item.id,  # type: ignore[arg-type]
            source=item.source,
            recipient_identifier=item.recipient_identifier,
            text=item.text,
            created_at=item.created_at.isoformat(),  # type: ignore[union-attr]
        )
        for item in pending
    ]


@app.post("/api/messaging/outbound/{message_id}/ack")
async def ack_messaging_outbound(message_id: int, request: MessagingOutboundAckRequest) -> dict[str, bool]:
    """Called by the external delivery process once it has attempted to
    send a queued reply — see modules/messaging/BRIDGE.md."""
    if request.status not in ("sent", "failed"):
        raise HTTPException(status_code=400, detail="status must be 'sent' or 'failed'")
    ok = await asyncio.to_thread(
        messaging_service_layer.mark_outbound_delivered,
        MessagingUnitOfWork(),
        message_id,
        request.status == "sent",
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Outbound message not found")
    return {"ok": True}


def _fitness_bio_profile_response(snapshot: FitnessBioProfileSnapshot) -> FitnessBioProfileResponse:
    assert snapshot.updated_at is not None
    category = fitness_calculations.get_bmi_category(snapshot.bmi, snapshot.sex) if snapshot.bmi is not None else None
    return FitnessBioProfileResponse(
        sex=snapshot.sex,
        age=snapshot.age,
        height_cm=snapshot.height_cm,
        weight_kg=snapshot.weight_kg,
        bmi=snapshot.bmi,
        bmi_category=category,
        updated_at=snapshot.updated_at.isoformat(),
    )


def _fitness_measurement_response(measurement: FitnessBodyMeasurement) -> FitnessMeasurementResponse:
    assert measurement.id is not None
    assert measurement.recorded_at is not None
    return FitnessMeasurementResponse(
        id=measurement.id,
        body_part=measurement.body_part,
        value_cm=measurement.value_cm,
        recorded_at=measurement.recorded_at.isoformat(),
    )


def _fitness_goal_response(goal: FitnessGoal) -> FitnessGoalResponse:
    assert goal.id is not None
    assert goal.created_at is not None
    return FitnessGoalResponse(
        id=goal.id,
        goal_type=goal.goal_type.value,
        description=goal.description,
        target_value=goal.target_value,
        unit=goal.unit,
        deadline=goal.deadline.isoformat() if goal.deadline else None,
        created_at=goal.created_at.isoformat(),
        achieved_at=goal.achieved_at.isoformat() if goal.achieved_at else None,
    )


def _fitness_meal_response(entry: FitnessMealLogEntry) -> FitnessMealResponse:
    assert entry.id is not None
    assert entry.logged_at is not None
    return FitnessMealResponse(
        id=entry.id,
        description=entry.description,
        estimated_calories=entry.estimated_calories,
        protein_g=entry.protein_g,
        fat_g=entry.fat_g,
        carbs_g=entry.carbs_g,
        confidence=entry.confidence,
        source=entry.source,
        has_photo=entry.photo_path is not None,
        logged_at=entry.logged_at.isoformat(),
    )


@app.get("/api/fitness/profile", response_model=FitnessBioProfileResponse | None)
async def get_fitness_profile() -> FitnessBioProfileResponse | None:
    profile = await asyncio.to_thread(fitness_service_layer.get_current_bio_profile)
    return _fitness_bio_profile_response(profile) if profile is not None else None


@app.post("/api/fitness/profile", response_model=FitnessBioProfileResponse)
async def update_fitness_profile(request: FitnessBioProfileUpdateRequest) -> FitnessBioProfileResponse:
    snapshot = await asyncio.to_thread(
        fitness_service_layer.update_bio_profile,
        sex=request.sex,
        age=request.age,
        height_cm=request.height_cm,
        weight_kg=request.weight_kg,
    )
    return _fitness_bio_profile_response(snapshot)


@app.get("/api/fitness/weight_history", response_model=list[FitnessWeightHistoryEntryResponse])
async def get_fitness_weight_history() -> list[FitnessWeightHistoryEntryResponse]:
    history = await asyncio.to_thread(fitness_service_layer.list_weight_history)
    return [
        FitnessWeightHistoryEntryResponse(weight_kg=entry.weight_kg, recorded_at=entry.updated_at.isoformat())  # type: ignore[union-attr]
        for entry in history
    ]


@app.get("/api/fitness/measurements", response_model=list[FitnessMeasurementResponse])
async def list_fitness_measurements(body_part: str | None = None) -> list[FitnessMeasurementResponse]:
    measurements = await asyncio.to_thread(fitness_service_layer.list_measurements, body_part)
    return [_fitness_measurement_response(m) for m in measurements]


@app.post("/api/fitness/measurements", response_model=FitnessMeasurementResponse)
async def add_fitness_measurement(request: FitnessMeasurementCreateRequest) -> FitnessMeasurementResponse:
    measurement = await asyncio.to_thread(fitness_service_layer.add_measurement, request.body_part, request.value_cm)
    return _fitness_measurement_response(measurement)


@app.get("/api/fitness/goals", response_model=list[FitnessGoalResponse])
async def list_fitness_goals() -> list[FitnessGoalResponse]:
    goals = await asyncio.to_thread(fitness_service_layer.list_goals)
    return [_fitness_goal_response(goal) for goal in goals]


@app.post("/api/fitness/goals", response_model=FitnessGoalResponse)
async def add_fitness_goal(request: FitnessGoalCreateRequest) -> FitnessGoalResponse:
    try:
        goal_type = FitnessGoalType(request.goal_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown goal_type: {request.goal_type}")
    deadline = date.fromisoformat(request.deadline) if request.deadline else None
    goal = await asyncio.to_thread(
        fitness_service_layer.add_goal, goal_type, request.description, request.target_value, request.unit, deadline
    )
    return _fitness_goal_response(goal)


@app.delete("/api/fitness/goals/{goal_id}")
async def delete_fitness_goal(goal_id: int) -> dict[str, bool]:
    deleted = await asyncio.to_thread(fitness_service_layer.delete_goal, goal_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Goal not found")
    return {"deleted": True}


@app.get("/api/fitness/meals", response_model=list[FitnessMealResponse])
async def list_fitness_meals(limit: int | None = None) -> list[FitnessMealResponse]:
    meals = await asyncio.to_thread(fitness_service_layer.list_meals, limit)
    return [_fitness_meal_response(meal) for meal in meals]


@app.post("/api/fitness/meals/text", response_model=FitnessMealResponse)
async def log_fitness_meal_text(request: FitnessMealTextRequest) -> FitnessMealResponse:
    try:
        analysis = await fitness_meal_analyzer.estimate_from_text(request.description, request.grams)
    except fitness_meal_analyzer.MealAnalysisError as exc:
        entry = await asyncio.to_thread(fitness_service_layer.log_meal, request.description, None, "low", "manual")
        logger.warning("Fitness meal text analysis failed, logged without an estimate: %s", exc)
        return _fitness_meal_response(entry)

    macros = analysis["macros"]
    entry = await asyncio.to_thread(
        fitness_service_layer.log_meal,
        analysis["description"],
        analysis["estimated_calories"],
        analysis["confidence"],
        "text",
        macros.get("protein_g"),
        macros.get("fat_g"),
        macros.get("carbs_g"),
    )
    return _fitness_meal_response(entry)


@app.post("/api/fitness/meals/photo", response_model=FitnessMealResponse)
async def log_fitness_meal_photo(photo: UploadFile = File(...), note: str | None = Form(None)) -> FitnessMealResponse:
    data = await photo.read()
    suffix = Path(photo.filename or "").suffix or ".jpg"
    saved_path = await asyncio.to_thread(fitness_progress_photos.save_photo_bytes, data, suffix)

    try:
        analysis = await fitness_meal_analyzer.estimate_from_photo(saved_path)
    except fitness_meal_analyzer.MealAnalysisError as exc:
        entry = await asyncio.to_thread(
            fitness_service_layer.log_meal, note or "Фото еды", None, "low", "photo", None, None, None, str(saved_path)
        )
        logger.warning("Fitness meal photo analysis failed, logged without an estimate: %s", exc)
        return _fitness_meal_response(entry)

    macros = analysis["macros"]
    entry = await asyncio.to_thread(
        fitness_service_layer.log_meal,
        analysis["description"],
        analysis["estimated_calories"],
        analysis["confidence"],
        "photo",
        macros.get("protein_g"),
        macros.get("fat_g"),
        macros.get("carbs_g"),
        str(saved_path),
    )
    return _fitness_meal_response(entry)


@app.get("/api/fitness/meals/{meal_id}/photo")
async def get_fitness_meal_photo(meal_id: int) -> FileResponse:
    meals = await asyncio.to_thread(fitness_service_layer.list_meals)
    entry = next((m for m in meals if m.id == meal_id), None)
    if entry is None or not entry.photo_path or not Path(entry.photo_path).is_file():
        raise HTTPException(status_code=404, detail="Meal photo not found")
    return FileResponse(entry.photo_path)


@app.delete("/api/fitness/meals/{meal_id}")
async def delete_fitness_meal(meal_id: int) -> dict[str, bool]:
    deleted = await asyncio.to_thread(fitness_service_layer.delete_meal, meal_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Meal not found")
    return {"deleted": True}


@app.get("/api/fitness/progress_photos", response_model=list[FitnessProgressPhotoResponse])
async def list_fitness_progress_photos() -> list[FitnessProgressPhotoResponse]:
    photos = await asyncio.to_thread(fitness_service_layer.list_progress_photos)
    return [
        FitnessProgressPhotoResponse(id=p.id, note=p.note, taken_at=p.taken_at.isoformat())  # type: ignore[union-attr]
        for p in photos
    ]


@app.post("/api/fitness/progress_photos", response_model=FitnessProgressPhotoResponse)
async def add_fitness_progress_photo(
    photo: UploadFile = File(...), note: str | None = Form(None)
) -> FitnessProgressPhotoResponse:
    data = await photo.read()
    suffix = Path(photo.filename or "").suffix or ".jpg"
    saved_path = await asyncio.to_thread(fitness_progress_photos.save_photo_bytes, data, suffix)
    record = await asyncio.to_thread(fitness_service_layer.add_progress_photo, str(saved_path), note)
    return FitnessProgressPhotoResponse(id=record.id, note=record.note, taken_at=record.taken_at.isoformat())  # type: ignore[union-attr]


@app.get("/api/fitness/progress_photos/{photo_id}/file")
async def get_fitness_progress_photo_file(photo_id: int) -> FileResponse:
    photos = await asyncio.to_thread(fitness_service_layer.list_progress_photos)
    record = next((p for p in photos if p.id == photo_id), None)
    if record is None or not Path(record.file_path).is_file():
        raise HTTPException(status_code=404, detail="Progress photo not found")
    return FileResponse(record.file_path)


@app.delete("/api/fitness/progress_photos/{photo_id}")
async def delete_fitness_progress_photo(photo_id: int) -> dict[str, bool]:
    photos = await asyncio.to_thread(fitness_service_layer.list_progress_photos)
    record = next((p for p in photos if p.id == photo_id), None)
    deleted = await asyncio.to_thread(fitness_service_layer.delete_progress_photo, photo_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Progress photo not found")
    if record is not None:
        await asyncio.to_thread(fitness_progress_photos.delete_photo_file, record.file_path)
    return {"deleted": True}


@app.post("/api/fitness/chat", response_model=FitnessChatResponse)
async def fitness_chat_message(request: FitnessChatRequest) -> FitnessChatResponse:
    try:
        reply = await fitness_chat.answer_question(request.text)
    except fitness_chat.FitnessChatError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return FitnessChatResponse(reply=reply)


_FRONTEND_DIST_DIR = BASE_DIR / "frontend" / "dist"
if _FRONTEND_DIST_DIR.is_dir():
    # Serves the built React frontend directly from this same FastAPI process,
    # so a phone on the LAN opens http://<this-machine-lan-ip>:{port}/ and gets
    # the identical UI same-origin (no CORS needed) — the "phone as thin
    # client" path. Mounted last so it never shadows the /api/* routes above.
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST_DIR, html=True), name="frontend")
else:
    logger.warning(
        "Frontend build not found at %s; skipping static mount. Run `npm run build:vite` "
        "in frontend/ to serve the UI over HTTP for LAN/phone clients.",
        _FRONTEND_DIST_DIR,
    )
