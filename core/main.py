from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from core.bootstrap import compose
from core.command_ui_metadata import COMMAND_UI_METADATA
from core.config import BASE_DIR, DATA_DIR, detect_lan_ip, settings
from core.dispatcher import UnknownCommandError
from core.logger import get_logger
from core.message_bus import message_bus
from core.models import (
    AIBridgeStatus,
    CommandButtonDescriptor,
    CommandDescriptor,
    CommandParamField,
    CommandRequest,
    CommandResponse,
    ConfirmRequest,
    CustomCommandListResponse,
    CustomCommandResponse,
    GameAnswerRequest,
    GameStartRequest,
    GameStateResponse,
    ImageRequest,
    LanUrlResponse,
    LibrarySetResponse,
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
    QuizletAuthStatus,
    QuizletLibraryResponse,
    SaveStudySetRequest,
    SelectVoiceRequest,
    SpeakRequest,
    SpeakResponse,
    StatusResponse,
    StudySetListResponse,
    StudySetResponse,
    TermResponse,
    TextQueryRequest,
    UIVisibilityRequest,
    VoiceGameAnswerResponse,
    VoiceGameStartResponse,
    VoiceLoopStatus,
    VoiceOptionsResponse,
    VoiceQueryResponse,
    WordPressJobStatusResponse,
    WordPressUploadResponse,
)
from core.state import state_manager
from core.voice import web_pipeline
from modules.ai_bridge import provider_auth, virtual_display
from modules.ai_bridge.provider_manager import get_provider_manager
from modules.custom_commands import dispatcher as custom_commands_registry
from modules.custom_commands import service_layer as custom_commands_service_layer
from modules.custom_commands.domain import ActionType
from modules.custom_commands.uow import CustomCommandsUnitOfWork
from modules.figma_control.ws_server import WEBSOCKET_PATH as FIGMA_WEBSOCKET_PATH
from modules.figma_control.ws_server import figma_ws_server
from modules.meeting_recorder import service_layer as meeting_service_layer
from modules.meeting_recorder.domain import Recording as MeetingRecording
from modules.meeting_recorder.domain import RecordingStatus as MeetingRecordingStatus
from modules.meeting_recorder.domain import SummaryStatus as MeetingSummaryStatus
from modules.meeting_recorder.domain import TranscriptStatus as MeetingTranscriptStatus
from modules.meeting_recorder.uow import MeetingRecordingUnitOfWork
from modules.messaging import service_layer as messaging_service_layer
from modules.messaging.uow import MessagingUnitOfWork
from modules.quizlet_clone import game_modes as quizlet_game_modes
from modules.quizlet_clone import quizlet_auth, quizlet_scraper
from modules.quizlet_clone import service_layer as quizlet_service_layer
from modules.quizlet_clone.models import GameMode as QuizletGameMode
from modules.quizlet_clone.storage import QuizletUnitOfWork as QuizletCloneUnitOfWork
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


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    logger.info("Assistant core service starting up")
    if settings.voice_autostart:
        voice_loop.start()
    reminder_checker.start()
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
    yield
    voice_loop.stop()
    reminder_checker.stop()
    hardware_monitor.stop()
    recording_processor.stop()
    recording_transcriber.stop()
    messaging_snooze_checker.stop()
    gmail_poller.stop()
    await get_provider_manager().close_all()
    virtual_display.stop()
    await quizlet_auth.get_session().close()
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
    is attached (see frontend/src/api/client.ts)."""
    if request.method != "OPTIONS" and request.url.path.startswith("/api/"):
        header_token = request.headers.get(_TOKEN_HEADER)
        query_token = request.query_params.get("token")
        if settings.api_token not in (header_token, query_token):
            return JSONResponse(status_code=401, content={"detail": "Missing or invalid API token."})
    response: Response = await call_next(request)
    return response


@app.get("/api/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    return StatusResponse(state=state_manager.state, detail=state_manager.detail)


@app.get("/api/commands", response_model=list[CommandDescriptor])
async def list_commands() -> list[CommandDescriptor]:
    return dispatcher.list_commands()


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
    return await dispatcher.confirm(request.token, request.approved)


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


def _quizlet_term_to_response(term: Any) -> TermResponse:
    return TermResponse(
        id=term.id,
        term=term.term,
        definition=term.definition,
        times_seen=term.times_seen,
        times_correct=term.times_correct,
        times_wrong=term.times_wrong,
        learned=term.learned,
    )


def _quizlet_set_to_response(study_set: Any) -> StudySetResponse:
    return StudySetResponse(
        id=study_set.id,
        title=study_set.title,
        source=study_set.source.value,
        quizlet_set_id=study_set.quizlet_set_id,
        created_at=study_set.created_at.isoformat() if study_set.created_at else "",
        progress_percent=study_set.progress_percent,
        attempts_count=study_set.attempts_count,
        terms=[_quizlet_term_to_response(t) for t in study_set.terms],
    )


@app.get("/api/quizlet/status", response_model=QuizletAuthStatus)
async def get_quizlet_status() -> QuizletAuthStatus:
    return QuizletAuthStatus(logged_in=await quizlet_auth.is_logged_in())


@app.get("/api/quizlet/sets", response_model=StudySetListResponse)
async def list_quizlet_sets() -> StudySetListResponse:
    sets = quizlet_service_layer.list_sets(QuizletCloneUnitOfWork())
    return StudySetListResponse(sets=[_quizlet_set_to_response(s) for s in sets])


@app.post("/api/quizlet/sets", response_model=StudySetResponse)
async def save_quizlet_set(request: SaveStudySetRequest) -> StudySetResponse:
    """Create (set_id omitted) or fully replace (set_id set) a manually
    entered study set — JSON counterpart of POST /api/custom_commands's
    create-or-update-by-optional-id shape, without that route's multipart/
    file handling (no attachments here)."""
    pairs = [(t.term.strip(), t.definition.strip()) for t in request.terms if t.term.strip() and t.definition.strip()]
    if not pairs:
        raise HTTPException(status_code=400, detail="At least one non-empty term/definition pair is required")

    uow = QuizletCloneUnitOfWork()
    if request.set_id:
        study_set = quizlet_service_layer.update_set(uow, request.set_id, request.title, pairs)
        if study_set is None:
            raise HTTPException(status_code=404, detail=f"Unknown study set: {request.set_id}")
    else:
        study_set = quizlet_service_layer.create_manual_set(uow, request.title, pairs)
    return _quizlet_set_to_response(study_set)


@app.delete("/api/quizlet/sets/{set_id}")
async def delete_quizlet_set(set_id: str) -> dict[str, bool]:
    removed = quizlet_service_layer.delete_set(QuizletCloneUnitOfWork(), set_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Unknown study set: {set_id}")
    return {"removed": True}


@app.get("/api/quizlet/library", response_model=QuizletLibraryResponse)
async def list_quizlet_library() -> QuizletLibraryResponse:
    session = quizlet_auth.get_session()
    if not await session.is_logged_in():
        raise HTTPException(status_code=409, detail="Сначала войдите в Quizlet.")
    try:
        library = await quizlet_scraper.list_library_sets(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    local_sets = quizlet_service_layer.list_sets(QuizletCloneUnitOfWork())
    local_by_quizlet_id = {s.quizlet_set_id: s for s in local_sets if s.quizlet_set_id}
    return QuizletLibraryResponse(
        sets=[
            LibrarySetResponse(
                quizlet_set_id=item.quizlet_set_id,
                title=item.title,
                term_count=item.term_count,
                already_imported=item.quizlet_set_id in local_by_quizlet_id,
                local_set_id=(
                    local_by_quizlet_id[item.quizlet_set_id].id if item.quizlet_set_id in local_by_quizlet_id else None
                ),
            )
            for item in library
        ]
    )


def _parse_quizlet_game_mode(mode: str) -> QuizletGameMode:
    try:
        return QuizletGameMode(mode)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown game mode: {mode}") from None


@app.post("/api/quizlet/game/start", response_model=GameStateResponse)
async def start_quizlet_game(request: GameStartRequest) -> GameStateResponse:
    mode = _parse_quizlet_game_mode(request.mode)
    if mode is QuizletGameMode.VOICE:
        raise HTTPException(status_code=400, detail="Голосовой режим запускается через /api/quizlet/voice/start")

    distractor_pool: list[str] | None = None
    if mode is QuizletGameMode.TEST:
        # Fallback distractor pool for sets with fewer than 4 terms of their
        # own — pulled from every other local set (ТЗ п.3's "генерация
        # неверных вариантов ... случайный выбор определений из того же
        # набора", extended to other sets only when this one alone can't
        # supply 3 distractors — see game_modes.TestSession).
        all_sets = quizlet_service_layer.list_sets(QuizletCloneUnitOfWork())
        distractor_pool = [t.definition for s in all_sets if s.id != request.set_id for t in s.terms]

    try:
        session_id, state = quizlet_game_modes.start(
            QuizletCloneUnitOfWork(), request.set_id, mode, distractor_pool=distractor_pool
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GameStateResponse(session_id=session_id, state=state)


@app.get("/api/quizlet/game/{session_id}", response_model=GameStateResponse)
async def get_quizlet_game_state(session_id: str) -> GameStateResponse:
    try:
        state = quizlet_game_modes.get_state(session_id)
    except quizlet_game_modes.UnknownSessionError:
        raise HTTPException(status_code=404, detail=f"Unknown game session: {session_id}") from None
    return GameStateResponse(session_id=session_id, state=state)


@app.post("/api/quizlet/game/{session_id}/answer", response_model=GameStateResponse)
async def answer_quizlet_game(session_id: str, request: GameAnswerRequest) -> GameStateResponse:
    try:
        state = quizlet_game_modes.answer(QuizletCloneUnitOfWork(), session_id, request.payload)
    except quizlet_game_modes.UnknownSessionError:
        raise HTTPException(status_code=404, detail=f"Unknown game session: {session_id}") from None
    except (ValueError, quizlet_game_modes.GameOverError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GameStateResponse(session_id=session_id, state=state)


@app.post("/api/quizlet/voice/start", response_model=VoiceGameStartResponse)
async def start_quizlet_voice_game(request: GameStartRequest) -> VoiceGameStartResponse:
    """Голосовой режим (ТЗ п.3), implemented as a stateful turn-based HTTP
    flow rather than a spoken trigger phrase inside core/voice/pipeline.py's
    always-on wake-word mic loop: that loop only reacts to the desktop's own
    microphone via a fixed set of rule-matched phrases (see
    VoiceAssistantLoop._resolve_board_game's docstring on why board games
    and messaging replies are scoped to it specifically) and launching a
    second concurrent capture from the same device would contend for the
    mic. Here the browser records each answer instead (the same
    MediaRecorder flow VoiceRecorder.tsx already uses for
    POST /api/voice/query), and turn state lives server-side in
    modules.quizlet_clone.game_modes, keyed by session_id, across requests —
    so this stays a stateless-per-request endpoint despite the multi-turn
    game underneath."""
    try:
        session_id, state = quizlet_game_modes.start(QuizletCloneUnitOfWork(), request.set_id, QuizletGameMode.VOICE)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    term_text = state.get("term")
    audio_b64 = await asyncio.to_thread(web_pipeline.synthesize_speech, term_text, "ru") if term_text else None
    return VoiceGameStartResponse(
        session_id=session_id,
        finished=state.get("finished", False),
        term_text=term_text,
        term_audio_base64=audio_b64,
        remaining=state.get("remaining", 0),
        total=state.get("total", 0),
    )


@app.post("/api/quizlet/voice/answer", response_model=VoiceGameAnswerResponse)
async def answer_quizlet_voice_game(
    session_id: str = Form(...), audio: UploadFile = File(...), language: str | None = Form(None)
) -> VoiceGameAnswerResponse:
    data = await audio.read()
    try:
        transcribed_text = await web_pipeline.transcribe_uploaded_audio(data, audio.filename or "audio.webm", language)
    except web_pipeline.InvalidAudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        result = quizlet_game_modes.answer_spoken(QuizletCloneUnitOfWork(), session_id, transcribed_text)
    except quizlet_game_modes.UnknownSessionError:
        raise HTTPException(status_code=404, detail=f"Unknown game session: {session_id}") from None
    except (ValueError, quizlet_game_modes.GameOverError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    correct = bool(result.get("correct"))
    result_text = "Верно!" if correct else f"Неверно. Правильный ответ: {result.get('expected_definition', '')}"
    result_audio_b64 = await asyncio.to_thread(web_pipeline.synthesize_speech, result_text, "ru")

    finished = bool(result.get("finished"))
    next_term_text = None if finished else result.get("term")
    next_term_audio_b64 = (
        await asyncio.to_thread(web_pipeline.synthesize_speech, next_term_text, "ru") if next_term_text else None
    )

    return VoiceGameAnswerResponse(
        session_id=session_id,
        transcribed_text=transcribed_text,
        correct=correct,
        answered_term=result.get("answered_term", ""),
        expected_definition=result.get("expected_definition", ""),
        result_audio_base64=result_audio_b64,
        finished=finished,
        next_term_text=next_term_text,
        next_term_audio_base64=next_term_audio_b64,
        remaining=result.get("remaining", 0),
        total=result.get("total", 0),
    )


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
