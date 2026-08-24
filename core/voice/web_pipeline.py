from __future__ import annotations

import asyncio
import base64
import io
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from core.dispatcher import CommandDispatcher
from core.logger import get_logger
from core.voice import ai_router, voice_preference
from modules.app_catalog import resolver as app_resolver
from modules.calendar import extraction as calendar_extraction
from modules.custom_commands import dispatcher as custom_commands_registry
from modules.custom_commands.domain import ActionType
from modules.hardware_adaptive import command_classifier
from modules.media import query_correction as media_query_correction
from modules.media import youtube as media_youtube
from modules.task_orchestrator import announce as task_orchestrator_announce
from modules.task_orchestrator import service_layer as task_orchestrator_service_layer
from modules.ui_automation import announce as ui_announce
from modules.ui_automation import service_layer as ui_service_layer
from core.voice.config import voice_settings
from core.voice.intent import Command, interpret, is_affirmative
from core.voice.language import resolve_language, resolve_response_language
from core.voice.plugin_match import match_plugin_command
from core.voice.responses import localize_response, not_understood
from core.voice.silero_tts import VOICE_OPTIONS
from core.voice.stt import SpeechToText
from core.voice.tts import TextToSpeech

logger = get_logger(__name__)

# Both faster-whisper (STT) and piper-tts (TTS) hold model weights in memory
# once loaded; a single process-wide instance of each avoids reloading them
# per HTTP request from a phone/browser thin client.
_stt = SpeechToText(voice_settings)
_tts = TextToSpeech(voice_settings)


class InvalidAudioError(ValueError):
    """Uploaded audio is empty or not a decodable audio file — a client
    mistake (HTTP 400), not a server fault."""


@dataclass(frozen=True)
class VoiceQueryResult:
    transcribed_text: str
    reply_text: str
    language: str
    audio_wav_base64: str | None
    status: str | None
    token: str | None


def _decode_uploaded_audio(data: bytes, suffix: str) -> Any:
    """Decodes an arbitrary browser-recorded audio blob (webm/opus, ogg, wav,
    ...) the same way modules.crm_transcribe.transcriber does: via
    faster-whisper's ffmpeg-backed decode_audio helper, through a temp file
    since it only accepts a path."""
    if not data:
        raise InvalidAudioError("Uploaded audio file is empty.")

    try:
        from faster_whisper.audio import decode_audio
    except ImportError:
        from faster_whisper import decode_audio  # type: ignore[attr-defined]

    with tempfile.NamedTemporaryFile(suffix=suffix or ".webm") as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            return decode_audio(tmp.name, sampling_rate=voice_settings.sample_rate)
        except Exception as exc:
            raise InvalidAudioError(f"Could not decode uploaded audio: {exc}") from exc


def synthesize_speech(text: str, language: str, speaker: str | None = None) -> str | None:
    """Synthesizes `text` and returns it as a base64-encoded 16-bit PCM WAV
    string the browser can play directly (`Audio` / `<audio>` with a
    `data:audio/wav;base64,` URI) — or None if synthesis isn't possible (e.g.
    no Piper voice available), so the caller can degrade to text-only.

    `speaker`, if given, previews that Silero voice for this call only
    without changing the persisted default (see core.voice.voice_preference)."""
    if not text:
        return None
    try:
        samples, sample_rate = _tts.synthesize(text, language, speaker=speaker)
    except RuntimeError as exc:
        logger.exception("TTS synthesis failed: %s", exc)
        return None
    if samples.size == 0:
        return None

    pcm16 = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm16.tobytes())
    return base64.b64encode(buffer.getvalue()).decode("ascii")


async def transcribe_uploaded_audio(audio_bytes: bytes, filename: str, language: str | None = None) -> str:
    """Decode+transcribe half of process_voice_query, pulled out standalone
    for callers that don't need the full interpret/dispatch pipeline —
    e.g. core/main.py's /api/voice/transcribe, used by one-shot mic-to-field
    voice input on the frontend (frontend/src/hooks/useOneShotVoiceInput.ts)
    that should only fill a text field, not be resolved as a command."""
    suffix = Path(filename).suffix
    audio = await asyncio.to_thread(_decode_uploaded_audio, audio_bytes, suffix)
    transcription = await asyncio.to_thread(_stt.transcribe, audio, language)
    return transcription.text.strip()


def list_voices() -> tuple[list[dict[str, str]], str]:
    """All selectable voices plus the currently selected speaker id, for the
    voice-settings UI."""
    voices = [
        {"speaker": option.speaker, "label": option.label, "gender": option.gender}
        for option in VOICE_OPTIONS
    ]
    return voices, voice_preference.get_selected_speaker()


def select_voice(speaker: str) -> None:
    voice_preference.set_selected_speaker(speaker)


async def _resolve_and_dispatch(
    dispatcher: CommandDispatcher, text: str, input_language: str, response_language: str
) -> tuple[str, str | None, str | None]:
    """The interpret -> plugin match -> ai_router -> dispatch pipeline shared
    by process_voice_query (text from Whisper transcription) and
    process_text_query (text typed directly into the desktop UI) — kept in
    one place so the two entry points can't drift on how a command actually
    gets resolved. Returns (reply_text, status, token)."""
    # Custom commands (modules/custom_commands) are checked before even the
    # rule-based interpret() here too, same priority core/voice/pipeline.py's
    # live mic loop gives them (see that method's own comment) — previously
    # this endpoint never checked them at all, so a custom trigger phrase
    # only ever worked from the desktop mic, never from the phone/LAN thin
    # client or the typed-text box that both call into this function.
    text_to_interpret = text
    reply_text: str | None = None
    command: Command | None = None

    custom_match = custom_commands_registry.match(text)
    if custom_match is not None:
        needs_confirmation = (
            custom_match.action_type in (ActionType.LAUNCH_APP, ActionType.TEXT_INSTRUCTION)
            and custom_commands_registry.requires_confirmation()
        )
        if needs_confirmation:
            # Confirming out loud needs the live mic loop's own follow-up
            # turn (core/voice/pipeline.py's _confirm_custom_command) — this
            # stateless request/response endpoint has nowhere to hold that,
            # same reasoning as start_board_game/messaging_reply below.
            # Refusing here keeps the confirmation gate meaningful instead
            # of silently bypassing it from the phone/LAN/typed-text paths —
            # checked for TEXT_INSTRUCTION here too, before the
            # substitute-and-continue branch below ever gets a chance to
            # skip the gate entirely.
            reply_text = (
                f"Команда «{custom_match.trigger_phrase}» требует подтверждения — "
                "выполните её через голосового ассистента на компьютере."
            )
        elif custom_match.action_type is ActionType.TEXT_INSTRUCTION:
            # Same substitute-and-continue-once handling as core/voice/pipeline.py:
            # a TEXT_INSTRUCTION command is a personal shortcut for a longer
            # request, never dispatched directly (see
            # modules/custom_commands/dispatcher.py's register_one docstring).
            text_to_interpret = custom_match.action_payload.get("instruction", "")
        else:
            command = Command(name=custom_commands_registry.dispatcher_command_name(custom_match.id), params={})

    if command is None and reply_text is None:
        command = interpret(text_to_interpret, input_language) or match_plugin_command(text_to_interpret)

    if command is None and reply_text is None:
        # Same fast, fully local system-command filter as core/voice/pipeline.py's
        # mic loop — see modules/hardware_adaptive/command_classifier.py.
        # Offloaded to a thread (unlike interpret()/match_plugin_command above,
        # which are cheap regex): the embedding encode is ~20-30ms of real CPU
        # work, and this function runs on the shared FastAPI event loop, not
        # pipeline.py's own dedicated voice-loop thread — blocking it here
        # would stall every other in-flight request for that long. Same
        # to_thread treatment modules.hardware_adaptive.local_ai already gives
        # its own CPU-bound local-model calls.
        command = await asyncio.to_thread(command_classifier.match_system_command, text_to_interpret)

    if command is None and reply_text is None:
        command, reply_text = await ai_router.resolve_free_text(text_to_interpret, dispatcher.list_commands())

    if command is not None and command.name == "schedule_event":
        # No multi-turn "what and when?" here either (see open_app/open_media
        # below for why) — only a request that already gave enough detail in
        # one utterance can be resolved; a bare "напомни мне" is told to be
        # more specific instead of guessing.
        raw_text = command.params.get("raw_text", "").strip()
        extracted = None
        if raw_text:
            try:
                extracted = await calendar_extraction.extract_event(raw_text)
            except Exception:
                logger.exception("Event extraction failed; using raw spoken text")
        if extracted is not None:
            command = Command(
                name="calendar_create_event",
                params={
                    "title": extracted.title,
                    "event_time": extracted.event_time.isoformat(),
                    "remind_before_minutes": str(extracted.remind_before_minutes),
                    "recurrence": extracted.recurrence.value,
                    "category": extracted.category,
                },
            )
        else:
            command = None
            reply_text = not_understood(response_language)

    if command is not None and command.name == "open_media":
        # No multi-turn "what's your mood?" here either (see the open_app
        # handling below for why) — only a request that already named a
        # specific title/topic can be resolved in one shot; a bare "включи
        # музыку" is told to be more specific instead of guessing.
        query = command.params.get("query", "").strip()
        if query:
            # See modules.media.query_correction: raw STT text for a foreign
            # (usually English) title routinely comes back as a Cyrillic
            # phonetic transliteration that searches nothing like the real
            # thing — this asks an AI adapter to fix that before building the
            # search URL. Falls back to the original text on failure, never
            # raises.
            query = await media_query_correction.correct_query(query)
            target = media_youtube.build_search_url(query)
            command = Command(name=command.name, params={**command.params, "target": target})
        else:
            command = None
            reply_text = not_understood(response_language)

    if command is not None and command.name == "open_app":
        # No multi-turn "did you mean X?" here — this is a stateless
        # request/response endpoint (see this module's docstrings), so
        # there's nowhere to hold a pending confirmation between requests.
        # Only the confident branch of core/voice/pipeline.py's resolution
        # applies: swap the target when sure, otherwise fall back to the
        # raw spoken text exactly as before this feature existed.
        try:
            resolved = await app_resolver.resolve(command.params.get("target", ""))
        except Exception:
            logger.exception("App/game target resolution failed; using raw spoken text")
            resolved = None
        if resolved is not None and resolved.is_confident:
            command = Command(name=command.name, params={**command.params, "target": resolved.app.launch_target})

    if command is not None and command.name == "ui_action":
        # No "speak, then act" ordering here (unlike core/voice/pipeline.py's
        # _resolve_ui_action) — this is a stateless request/response
        # endpoint with nowhere to hold a spoken announcement before
        # dispatch. ui_action is dangerous=True (see modules/ui_automation/
        # handlers.py), so dispatch() below doesn't actually click/type
        # anything either: like every other dangerous command through this
        # endpoint, it only returns CONFIRMATION_REQUIRED + a token, and the
        # real action runs later, from POST /api/command/confirm, once the
        # client has shown/read back reply_text and the user has agreed —
        # that confirmation step is what stands in for the live voice
        # loop's spoken announcement here.
        raw_text = command.params.get("raw_text", "").strip()
        steps = None
        if raw_text:
            try:
                steps = await ui_service_layer.ground_instruction(raw_text)
            except Exception:
                logger.exception("UI action grounding failed; giving up on this request")
        if steps:
            announcement = ui_announce.describe_steps(steps, response_language)
            command = Command(
                name=command.name,
                params={"steps": ui_service_layer.to_command_params(steps), "announcement": announcement},
            )
        else:
            command = None
            reply_text = not_understood(response_language)

    if command is not None and command.name == "run_task_plan":
        # Same stateless-endpoint reasoning as ui_action just above: no
        # "speak, then act" ordering here, and run_task_plan is
        # dangerous=True (see modules/task_orchestrator/handlers.py), so
        # dispatch() below returns CONFIRMATION_REQUIRED + a token rather
        # than actually running anything — the real execution happens
        # later, from POST /api/command/confirm, once the client has
        # shown/read back reply_text and the user has agreed.
        raw_text = command.params.get("raw_text", "").strip()
        task_plan = None
        if raw_text:
            try:
                task_plan = await task_orchestrator_service_layer.build_plan(raw_text, dispatcher)
            except Exception:
                logger.exception("Task plan building failed; giving up on this request")
        if task_plan and task_plan.steps:
            announcement = task_orchestrator_announce.describe_plan(task_plan, response_language)
            command = Command(
                name=command.name,
                params={
                    "steps": [{"command": step.command, "params": step.params} for step in task_plan.steps],
                    "announcement": announcement,
                },
            )
        else:
            command = None
            reply_text = not_understood(response_language)

    if command is not None and command.name == "start_board_game":
        # Scoped to the live mic voice loop only (see
        # core/voice/pipeline.py::_resolve_board_game) — a whole game is an
        # unbounded number of voice round-trips, which this stateless
        # request/response endpoint has nowhere to hold between requests,
        # same reasoning as messaging_reply/messaging_snooze just below.
        command = None
        reply_text = "Играть в шахматы или шашки можно только через голосового ассистента на компьютере."

    if command is not None and command.name == "start_os_agent":
        # Scoped to the live mic voice loop only (see core/voice/pipeline.py's
        # _resolve_os_agent_start/_resolve_active_os_agent_utterance) — same
        # reasoning as start_board_game just above: agent mode is an
        # unbounded number of voice round-trips (wait for the task, run the
        # autonomous loop, ask for a spoken confirm), which this stateless
        # request/response endpoint has nowhere to hold between requests.
        command = None
        reply_text = "Режим агента доступен только через голосового ассистента на компьютере."

    if command is not None and command.name in ("messaging_reply", "messaging_snooze"):
        # Deliberately scoped to the live mic voice loop only (see
        # core/voice/pipeline.py's _resolve_messaging_reply/_resolve_
        # messaging_snooze) — both need at least one more voice round-trip
        # (which pending message, what to actually say, how long to
        # snooze), which this stateless request/response endpoint has
        # nowhere to hold between requests, same reason schedule_event/
        # open_media/open_app above only ever take their single-shot,
        # already-unambiguous branch here. Rather than let this fall
        # through to dispatch() with raw_target/raw_text params the real
        # handler doesn't understand (producing a confusing generic
        # "Missing required parameter 'message_id'"), say plainly that
        # this isn't supported from here.
        command = None
        reply_text = (
            "Ответить или отложить сообщение можно только через голосового ассистента "
            "на компьютере, не отсюда."
        )

    status: str | None = None
    token: str | None = None

    if command is not None:
        response = await dispatcher.dispatch(command.name, command.params)
        reply_text = localize_response(response, response_language)
        status = response.status.value
        token = response.token
    elif reply_text is None:
        reply_text = not_understood(response_language)

    return reply_text, status, token


async def process_voice_query(
    dispatcher: CommandDispatcher, audio_bytes: bytes, filename: str, language: str | None = None
) -> VoiceQueryResult:
    """The phone/browser thin-client counterpart of
    VoiceAssistantLoop._handle_command: takes an uploaded audio blob instead
    of a live microphone recording, but otherwise runs the exact same
    interpret -> plugin match -> ai_router -> dispatch pipeline, then
    synthesizes the reply to speech. Stateless per request; a
    confirmation_required response is resolved by the client calling the
    existing POST /api/command/confirm with the returned token, same as the
    desktop UI does for non-voice commands.

    `language`, when given (from the browser's language toggle), is passed
    straight to Whisper to pin decoding rather than relying on autodetect —
    see SpeechToText.transcribe and resolve_language."""
    suffix = Path(filename).suffix
    audio = await asyncio.to_thread(_decode_uploaded_audio, audio_bytes, suffix)
    transcription = await asyncio.to_thread(_stt.transcribe, audio, language)
    text = transcription.text.strip()
    logger.info(
        "STT transcribed (web/phone client): %r (detected_language=%s, probability=%.2f)",
        text, transcription.detected_language, transcription.language_probability,
    )

    decision = resolve_language(
        transcription.detected_language, transcription.language_probability, voice_settings, override=language
    )
    response_language = resolve_response_language(decision.resolved, voice_settings)

    if not text:
        reply_text = not_understood(response_language)
        return VoiceQueryResult(
            transcribed_text="",
            reply_text=reply_text,
            language=response_language,
            audio_wav_base64=await asyncio.to_thread(synthesize_speech, reply_text, response_language),
            status=None,
            token=None,
        )

    reply_text, status, token = await _resolve_and_dispatch(dispatcher, text, decision.resolved, response_language)

    return VoiceQueryResult(
        transcribed_text=text,
        reply_text=reply_text,
        language=response_language,
        audio_wav_base64=await asyncio.to_thread(synthesize_speech, reply_text, response_language),
        status=status,
        token=token,
    )


async def process_voice_confirmation(
    dispatcher: CommandDispatcher, audio_bytes: bytes, filename: str, token: str, language: str | None = None
) -> VoiceQueryResult:
    """Voice counterpart of POST /api/command/confirm: the thin-client
    conversation loop (frontend/src/components/VoiceRecorder.tsx) calls this
    instead of process_voice_query for the turn right after a
    confirmation_required reply, so the spoken answer ("да"/"нет") is
    checked with is_affirmative and resolved against `token` directly.

    Without this, that recording used to go through process_voice_query like
    any other turn - a bare "да" doesn't match any rule-based command and
    isn't a real question either, so it came back as a generic "не поняла
    команду" instead of ever reaching the pending confirmation at all
    (which then just sat there until its TTL expired)."""
    suffix = Path(filename).suffix
    audio = await asyncio.to_thread(_decode_uploaded_audio, audio_bytes, suffix)
    transcription = await asyncio.to_thread(_stt.transcribe, audio, language)
    text = transcription.text.strip()
    logger.info(
        "STT transcribed (voice confirmation turn): %r (detected_language=%s, probability=%.2f)",
        text, transcription.detected_language, transcription.language_probability,
    )

    decision = resolve_language(
        transcription.detected_language, transcription.language_probability, voice_settings, override=language
    )
    response_language = resolve_response_language(decision.resolved, voice_settings)

    approved = is_affirmative(text, decision.resolved)
    response = await dispatcher.confirm(token, approved)
    reply_text = localize_response(response, response_language)

    return VoiceQueryResult(
        transcribed_text=text,
        reply_text=reply_text,
        language=response_language,
        audio_wav_base64=await asyncio.to_thread(synthesize_speech, reply_text, response_language),
        status=response.status.value,
        token=response.token,
    )


async def process_text_query(
    dispatcher: CommandDispatcher, text: str, language: str | None = None
) -> VoiceQueryResult:
    """Typed-text counterpart of process_voice_query, for the desktop UI's
    keyboard input box: skips audio decoding and speech recognition
    entirely since the text is already known, but resolves it through the
    exact same interpret -> plugin match -> ai_router -> dispatch pipeline
    (see _resolve_and_dispatch) as a spoken query, so typing and speaking
    the same words produce the same result.

    No reply audio is synthesized — a typed question gets a typed answer
    back, not an unsolicited spoken interruption; `audio_wav_base64` is
    always None here (VoiceQueryResult's shape is reused as-is so the
    frontend can render both kinds of query with the same component)."""
    text = text.strip()
    input_language = language if language in voice_settings.supported_languages else voice_settings.fallback_language
    response_language = resolve_response_language(input_language, voice_settings)

    if not text:
        return VoiceQueryResult(
            transcribed_text="",
            reply_text=not_understood(response_language),
            language=response_language,
            audio_wav_base64=None,
            status=None,
            token=None,
        )

    reply_text, status, token = await _resolve_and_dispatch(dispatcher, text, input_language, response_language)

    return VoiceQueryResult(
        transcribed_text=text,
        reply_text=reply_text,
        language=response_language,
        audio_wav_base64=None,
        status=status,
        token=token,
    )
