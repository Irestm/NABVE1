from __future__ import annotations

import asyncio
import re
import threading

from core.dispatcher import CommandDispatcher
from core.logger import get_logger
from core.models import AssistantState, CommandStatus
from core.state import state_manager
from core.voice import ai_router, audio_io, wake_word
from core.voice.barge_in import BargeInMonitor
from core.voice.config import VoiceSettings, voice_settings
from core.voice.intent import Command, interpret, is_affirmative, is_resign_command, is_stop_command
from core.voice.interruption import TurnCancelled, run_cancellable
from core.voice.language import resolve_language, resolve_response_language
from core.voice.phrase_matching import fuzzy_contains_phrase
from core.voice.plugin_match import match_plugin_command
from core.voice.fact_extraction import extract_facts
from core.voice.responses import localize_response, not_understood
from core.voice.stt import SpeechToText
from core.voice.tts import TextToSpeech
from core.voice.wake_word import WakeWordDetector, get_wake_word_detector
from modules.app_catalog import resolver as app_resolver
from modules.board_games import announce as board_games_announce
from modules.board_games import service_layer as board_games_service_layer
from modules.board_games.domain import GameKind
from modules.calendar import extraction as calendar_extraction
from modules.media import query_correction as media_query_correction
from modules.media import recommender as media_recommender
from modules.media import youtube as media_youtube
from modules.messaging import service_layer as messaging_service_layer
from modules.messaging import text_cleanup as messaging_text_cleanup
from modules.messaging.domain import PendingMessage
from modules.messaging.duration import parse_duration_minutes
from modules.messaging.uow import MessagingUnitOfWork
from modules.task_orchestrator import announce as task_orchestrator_announce
from modules.task_orchestrator import service_layer as task_orchestrator_service_layer
from modules.ui_automation import announce as ui_announce
from modules.ui_automation import service_layer as ui_service_layer
from modules.user_profile import service_layer as profile_service_layer
from modules.user_profile.domain import STOP_WORD_KEY
from modules.user_profile.onboarding import run_onboarding
from modules.user_profile.uow import ProfileUnitOfWork

logger = get_logger(__name__)

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")

# Strips a trailing "в телеграме"/"в телеграм"/"in telegram" from a spoken
# "следи за X (в телеграме)" instruction — see _resolve_messaging_watch_contact.
# _normalize() in core/voice/intent.py already strips punctuation (including
# a leading '@') before this ever runs, so what's left is just the bare
# identifier text either way.
_TELEGRAM_SUFFIX_PATTERN = re.compile(r"\s*(?:в\s+телеграм[е]?|in\s+telegram)\s*$", re.IGNORECASE)

# Same idea, for "следи за X на почте/в gmail" — see
# _resolve_messaging_watch_contact, which tries both suffixes and lets
# whichever one actually stripped something decide the source.
_GMAIL_SUFFIX_PATTERN = re.compile(
    r"\s*(?:на\s+почте|в\s+gmail|на\s+email|in\s+gmail)\s*$", re.IGNORECASE
)


class _SentenceStreamSpeaker:
    """Feeds a streamed local-model answer (see
    core/voice/ai_router.py:resolve_free_text's `on_stream_chunk`) to TTS one
    completed sentence at a time, so the user hears the first sentence while
    the model is still generating the rest — instead of waiting for the
    whole reply, synthesizing it, and only then starting playback.

    The barge-in monitor thread isn't started until the first sentence is
    actually about to be spoken (see `_speak`), so if that first sentence
    turns out to look degenerate (see ai_router.is_degenerate_answer) and
    `_handle_sentence` aborts before ever calling `_speak`, there's nothing
    to tear down — the caller (ai_router's adapter loop) just falls through
    to the next adapter as if this one had raised any other error, and
    nothing has been spoken yet. Degeneration appearing later in an already
    partly-spoken stream isn't caught — by then something has already been
    said, so there's no clean way to take it back."""

    def __init__(
        self, tts: TextToSpeech, language: str, barge_in: BargeInMonitor, voice_stop_event: threading.Event
    ) -> None:
        self._tts = tts
        self._language = language
        self._barge_in = barge_in
        self._voice_stop_event = voice_stop_event
        self._buffer = ""
        self._first_sentence = True
        self.aborted = False
        self._playback_stop = threading.Event()
        self._interrupted = threading.Event()
        self._monitor_thread: threading.Thread | None = None

    async def feed(self, chunk: str) -> None:
        self._buffer += chunk
        parts = _SENTENCE_END.split(self._buffer)
        if len(parts) <= 1:
            return
        *complete, self._buffer = parts
        for sentence in complete:
            await self._handle_sentence(sentence)

    async def finish(self) -> bool:
        if not self.aborted and self._buffer.strip():
            await self._speak(self._buffer)
        self._playback_stop.set()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=1.0)
        return self._interrupted.is_set()

    async def _handle_sentence(self, sentence: str) -> None:
        if self._first_sentence:
            self._first_sentence = False
            if ai_router.is_degenerate_answer(sentence):
                self.aborted = True
                raise RuntimeError(f"Degenerate local model output: {sentence!r}")
        await self._speak(sentence)

    async def _speak(self, sentence: str) -> None:
        sentence = sentence.strip()
        if not sentence or self._interrupted.is_set() or self._voice_stop_event.is_set():
            return
        if self._monitor_thread is None:
            self._monitor_thread = threading.Thread(
                target=self._barge_in.run,
                args=(self._language, self._playback_stop, self._interrupted),
                daemon=True,
            )
            self._monitor_thread.start()
        try:
            samples, sample_rate = await asyncio.to_thread(self._tts.synthesize, sentence, self._language)
        except RuntimeError as exc:
            logger.error("TTS failed: %s", exc)
            return
        if not samples.size:
            return
        try:
            await asyncio.to_thread(audio_io.play_audio, samples, sample_rate, stop_event=self._playback_stop)
        except Exception:
            # A hardware/device failure here isn't the AI adapter's fault
            # (a different adapter wouldn't fix a broken speaker), so this
            # is handled like the TTS failure above — skip this sentence —
            # rather than raised. Letting it propagate out of feed()/
            # _handle_sentence() had two bugs: it left this method's own
            # barge-in monitor thread running forever (finish() never
            # reached the code that stops it), and — for any sentence past
            # the first — it made ai_router's adapter-fallback loop treat a
            # pure playback glitch as "this adapter's answer was bad,
            # discard it", silently dropping a perfectly good fallback
            # answer instead of speaking it.
            logger.exception("Audio playback failed mid-stream")


class VoiceAssistantLoop:
    def __init__(
        self,
        dispatcher: CommandDispatcher,
        settings: VoiceSettings = voice_settings,
    ) -> None:
        self._dispatcher = dispatcher
        self._settings = settings
        self._stop_event = threading.Event()
        # Separate from _stop_event on purpose: _stop_event tears the whole
        # loop/thread down (see stop()), while pausing (see
        # _wait_for_wake_or_pause) must leave it dormant-but-alive so the
        # stop word can wake it back up later.
        self._paused_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._barge_in = BargeInMonitor(settings)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="voice-loop")
        self._thread.start()
        logger.info("Voice assistant loop started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        state_manager.set_state(AssistantState.IDLE)
        logger.info("Voice assistant loop stopped")

    def _speak_safely(self, tts: TextToSpeech, text: str, language: str) -> bool:
        """Speaks `text`. Returns True if the user cut it off with a stop
        phrase partway through (see BargeInMonitor) — the caller should treat
        that as "go straight back to listening", not "finished talking"."""
        try:
            samples, sample_rate = tts.synthesize(text, language)
        except RuntimeError as exc:
            logger.error("TTS failed: %s", exc)
            return False
        if samples.size == 0:
            return False

        stop_event = threading.Event()
        interrupted = threading.Event()
        monitor_thread = threading.Thread(
            target=self._barge_in.run, args=(language, stop_event, interrupted), daemon=True
        )
        monitor_thread.start()
        try:
            audio_io.play_audio(samples, sample_rate, stop_event=stop_event)
        finally:
            stop_event.set()
            monitor_thread.join(timeout=1.0)
        return interrupted.is_set()

    def _run_onboarding_if_needed(self) -> None:
        if profile_service_layer.is_onboarded(ProfileUnitOfWork()):
            return
        state_manager.set_state(AssistantState.ONBOARDING, "Знакомство")
        try:
            run_onboarding(self._settings, self._stop_event)
        except Exception:
            logger.exception("Onboarding failed")
        state_manager.set_state(AssistantState.IDLE)

    def _wait_for_wake_or_pause(self, wake_detector: WakeWordDetector) -> bool:
        """Blocks until the wake word is heard (returns True, caller should
        proceed to _handle_command) or the whole loop should stop (returns
        False — self._stop_event fired).

        The stop word is re-read from the profile on every pass through this
        loop (each iteration is one ~2s listening window, so this is a cheap
        sqlite read at that cadence, not a hot loop) rather than captured
        once when the thread started — it used to be fetched once in _run()
        before this method even existed as a loop, which meant setting a
        stop word for the first time via the personality settings panel (see
        modules/user_profile/handlers.py's profile_set) had no effect at all
        until the whole assistant was restarted: this method had already
        captured "no stop word" and never looked again.

        If a stop word is configured, it's listened for in the same pass as
        the wake word (see core/voice/wake_word.py's listen_for_phrases,
        which can't go through `wake_detector` itself — the Porcupine
        backend is a fixed offline keyword engine and can't recognize an
        arbitrary user-chosen phrase at all, so this always uses the
        STT-based listener once a stop word exists). Hearing it toggles
        self._paused_event and keeps looping internally instead of
        returning — pausing doesn't stop the thread, it just makes this
        method ignore the wake word until the same phrase is heard again."""
        while not self._stop_event.is_set():
            stop_word = profile_service_layer.get_fact(ProfileUnitOfWork(), STOP_WORD_KEY)

            if self._paused_event.is_set():
                if not stop_word:
                    # Nothing to resume on; shouldn't normally happen since
                    # pausing requires a stop word, but don't get stuck here.
                    self._paused_event.clear()
                    continue
                heard = wake_word.listen_for_phrases(
                    self._settings,
                    {"resume": stop_word},
                    self._stop_event,
                    model_size=self._settings.whisper_model_size,
                )
                if heard == "resume":
                    self._paused_event.clear()
                    state_manager.set_state(AssistantState.IDLE)
                    logger.info("Stop word heard again; resuming")
                continue

            if not stop_word:
                return wake_detector.listen(self._stop_event)

            # model_size=whisper_model_size (the bigger command tier, not
            # the fast wake-tier default): see wake_word.listen_for_phrases
            # for why an arbitrary user-chosen stop word needs the more
            # accurate model to be recognized reliably. This does make wake-
            # word detection itself a bit slower too, since both phrases are
            # checked in the same STT pass — but only for users who've
            # actually configured a stop word, and reliably honoring a pause
            # request matters more here than shaving time off wake latency.
            heard = wake_word.listen_for_phrases(
                self._settings,
                {"wake": self._settings.wake_word, "pause": stop_word},
                self._stop_event,
                model_size=self._settings.whisper_model_size,
            )
            if heard == "wake":
                return True
            if heard == "pause":
                self._paused_event.set()
                state_manager.set_state(AssistantState.PAUSED, "Скажите стоп-слово ещё раз, чтобы продолжить")
                logger.info("Stop word heard; pausing")

        return False

    def _run(self) -> None:
        wake_detector = get_wake_word_detector(self._settings)
        command_stt = SpeechToText(self._settings)
        tts = TextToSpeech(self._settings)

        self._run_onboarding_if_needed()

        # Set when the user barge-in-interrupted the previous reply with a
        # stop phrase: they're already mid-conversation, so the next turn
        # starts listening immediately instead of waiting for the wake word
        # again.
        listen_immediately = False
        while not self._stop_event.is_set():
            if not listen_immediately:
                try:
                    detected = self._wait_for_wake_or_pause(wake_detector)
                except Exception:
                    # continue (not return): a transient failure here — a
                    # brief audio-device hiccup, a one-off STT error — used
                    # to permanently kill the whole voice loop (ERROR state,
                    # thread exits) with nothing to auto-recover it, while
                    # the exact same category of transient failure in
                    # _handle_command just below already logs and keeps
                    # going. Mirror that: log with a traceback, report ERROR
                    # transiently, and let the next loop iteration retry the
                    # wake-word wait instead of ending the thread for good.
                    logger.exception("Wake-word detector failed")
                    state_manager.set_state(AssistantState.ERROR, "Ошибка распознавания слова пробуждения")
                    continue

                if not detected:
                    break

            try:
                listen_immediately = self._handle_command(command_stt, tts)
            except Exception:
                logger.exception("Voice command handling failed")
                state_manager.set_state(AssistantState.IDLE)
                listen_immediately = False

        state_manager.set_state(AssistantState.IDLE)

    def _classify_via_ai_bridge(
        self, text: str, command_stt: SpeechToText, tts: TextToSpeech, response_language: str
    ) -> tuple[Command | None, bool]:
        """Called when the built-in rule-based parser (`interpret`) found no
        match. Resolves the text via core/voice/ai_router.py — the local
        adaptive model first when hardware supports it and the query looks
        simple, else the ai_bridge fallback chain (Gemini -> ChatGPT ->
        DeepSeek -> Grok). Returns (command, interrupted): command is set to
        dispatch, or None if the text was answered directly (or nothing
        usable came back); interrupted is True if the user barge-in-cut off
        the spoken answer with a stop phrase.

        When the local model answers, its reply is streamed straight into
        TTS sentence by sentence via _SentenceStreamSpeaker (see
        ai_router.resolve_free_text's on_stream_chunk) instead of being
        spoken all at once after the fact — noticeably cuts the time to
        first audio. The ai_bridge chain can't stream (it's reading a full
        reply back from a web page), so that path is unchanged.

        After a direct answer finishes speaking without being barge-in-cut
        off, opens a short follow-up listening window (see
        _maybe_continue_free_text) instead of immediately returning to
        wake-word waiting — so "what's the weather" followed by "and
        tomorrow?" doesn't need the wake word said twice. Not applied when
        `text` resolved to a dispatchable `command` instead of a direct
        answer — that goes on to a real dispatch()/confirm() flow with its
        own response, not a second question here."""
        state_manager.set_state(AssistantState.THINKING, "Уточняю у ИИ")
        commands = self._dispatcher.list_commands()

        async def run() -> tuple[Command | None, str | None, bool | None]:
            speaker: _SentenceStreamSpeaker | None = None

            async def on_chunk(chunk: str) -> None:
                nonlocal speaker
                if speaker is None:
                    state_manager.set_state(AssistantState.SPEAKING)
                    speaker = _SentenceStreamSpeaker(tts, response_language, self._barge_in, self._stop_event)
                await speaker.feed(chunk)

            command, answer = await ai_router.resolve_free_text(text, commands, on_stream_chunk=on_chunk)
            if speaker is None or speaker.aborted:
                return command, answer, None
            return command, answer, await speaker.finish()

        try:
            command, answer, streamed_interrupted = asyncio.run(run())
        except Exception:
            logger.exception("AI intent classification failed")
            state_manager.set_state(AssistantState.SPEAKING)
            interrupted = self._speak_safely(tts, not_understood(response_language), response_language)
            return None, interrupted

        if command is not None:
            return command, False

        if streamed_interrupted is not None:
            if streamed_interrupted:
                return None, True
            return self._maybe_continue_free_text(command_stt, tts, response_language)

        state_manager.set_state(AssistantState.SPEAKING)
        if answer is None:
            interrupted = self._speak_safely(tts, not_understood(response_language), response_language)
            return None, interrupted

        interrupted = self._speak_safely(tts, answer, response_language)
        if interrupted:
            return None, True
        return self._maybe_continue_free_text(command_stt, tts, response_language)

    def _maybe_continue_free_text(
        self, command_stt: SpeechToText, tts: TextToSpeech, response_language: str
    ) -> tuple[Command | None, bool]:
        """After a free-text AI answer has finished speaking uninterrupted
        (see _classify_via_ai_bridge, the only caller), listens for a short
        bounded follow-up utterance instead of immediately returning to
        wake-word waiting. Silence within `follow_up_window_seconds` —
        nothing said at all — is the expected, common case (most answers
        don't get a follow-up) and just returns (None, False), same as
        before this feature existed. A captured follow-up recurses into
        _classify_via_ai_bridge with the new text, which can itself resolve
        to a real dispatchable command (handled normally by the caller) or
        open another round of this same follow-up window.

        Scoped to the free-text AI Q&A path only for now: a follow-up here
        always goes straight through ai_router's AI classifier, not
        core/voice/intent.py's fast rule-based parser — the fast-path
        regexes never see it. Widening this to every command type (i.e.
        re-running _handle_command's full pipeline on a follow-up) is a
        larger change than this first slice."""
        window = self._settings.follow_up_window_seconds
        if not window or window <= 0:
            return None, False

        state_manager.set_state(AssistantState.LISTENING, "Слушаю продолжение")
        audio = audio_io.record_until_silence(
            self._settings, self._stop_event, onset_timeout_seconds=window
        )
        if audio.size == 0:
            return None, False

        state_manager.set_state(AssistantState.PROCESSING, "Распознаю")
        result = command_stt.transcribe(audio)
        if not result.text.strip():
            return None, False

        return self._classify_via_ai_bridge(result.text, command_stt, tts, response_language)

    def _resolve_open_app_target(
        self, command: Command, command_stt: SpeechToText, tts: TextToSpeech, response_language: str, spoken_language: str
    ) -> tuple[Command | None, bool]:
        """Called for an "open_app" command before it's dispatched: tries to
        map its raw, possibly speech-garbled `target` param (e.g. "дед
        селс") to something actually installed on this machine (see
        modules.app_catalog.resolver), so a mangled game/app name has a
        chance of launching correctly instead of failing on
        shutil.which()/xdg-open with the literal spoken text.

        A confident resolution replaces `target` silently. Below the
        confidence threshold, asks "did you mean X?" first — same one-shot
        voice-confirmation shape as the dangerous-command confirmation in
        _handle_command below, just without the dispatcher token/pending-
        confirmation machinery (this confirms a parameter before dispatch,
        not a whole already-dispatched command). If resolution finds
        nothing at all (no local candidates, every AI adapter failed) or
        confirmation is declined, `command` is returned unchanged — this
        step only ever replaces the target, it never removes the fallback
        to the raw text that's all this command had before this feature
        existed.

        Returns (None, interrupted) only if the "did you mean X?" question
        itself got barge-in-cut-off mid-sentence — mirrors the dangerous-
        command confirmation's own handling of that case: abort rather than
        guess at an unheard answer."""
        try:
            resolved = run_cancellable(
                app_resolver.resolve(command.params.get("target", "")), self._barge_in, response_language
            )
        except TurnCancelled:
            raise
        except Exception:
            logger.exception("App/game target resolution failed; using raw spoken text")
            return command, False

        if resolved is None:
            return command, False

        resolved_command = Command(
            name=command.name, params={**command.params, "target": resolved.app.launch_target}
        )
        if resolved.is_confident:
            return resolved_command, False

        state_manager.set_state(AssistantState.SPEAKING)
        question = f"Вы имели в виду {resolved.app.display_name}?"
        if self._speak_safely(tts, question, response_language):
            return None, True

        state_manager.set_state(AssistantState.LISTENING, "Жду подтверждения")
        confirm_audio = audio_io.record_until_silence(self._settings, self._stop_event)
        confirm_result = command_stt.transcribe(confirm_audio)
        if is_affirmative(confirm_result.text, spoken_language):
            return resolved_command, False

        return command, False

    def _resolve_media_target(
        self, command: Command, command_stt: SpeechToText, tts: TextToSpeech, response_language: str
    ) -> tuple[Command | None, bool]:
        """Called for an "open_media" command before it's dispatched (see
        core/voice/intent.py's _MEDIA_PATTERNS): if the user named a
        specific title/topic ("видео с котиками"), builds a YouTube search
        URL for it directly. If they didn't ("включи музыку" with nothing
        else), asks "какое у вас сегодня настроение?" first, sends the
        answer to whichever AI adapter is available for a recommendation
        (modules.media.recommender), and searches YouTube for that instead.

        Returns (None, interrupted) if the mood question itself got
        barge-in-cut off, or if nothing usable came back at all (empty mood
        answer, every recommendation adapter failed) — unlike
        _resolve_open_app_target, there's no raw-target fallback that makes
        sense here (there's no file/executable literally named "музыку" to
        fall back to opening), so giving up entirely is the only sane
        option left."""
        kind = command.params.get("kind", "video")
        query = command.params.get("query", "").strip()

        if query:
            # The user already named a specific title/topic, so STT's raw
            # text goes straight into the search — but if that title is a
            # foreign (usually English) word, speech recognition routinely
            # mangles it into a Cyrillic phonetic transliteration ("дед
            # селс" for "Dead Cells") that searches nothing like the real
            # thing, so this used to only find the right video on a lucky
            # second attempt. correct_query never raises and falls back to
            # the original text on failure, so this is safe even when every
            # AI adapter is unavailable.
            query = run_cancellable(
                media_query_correction.correct_query(query), self._barge_in, response_language
            )
        else:
            state_manager.set_state(AssistantState.SPEAKING)
            if self._speak_safely(tts, "Какое у вас сегодня настроение?", response_language):
                return None, True

            state_manager.set_state(AssistantState.LISTENING, "Жду ответа")
            mood_audio = audio_io.record_until_silence(self._settings, self._stop_event)
            mood_text = command_stt.transcribe(mood_audio).text.strip()
            if not mood_text:
                return None, False

            try:
                query = run_cancellable(
                    media_recommender.recommend(kind, mood_text), self._barge_in, response_language
                )
            except TurnCancelled:
                raise
            except Exception:
                logger.exception("Media recommendation failed; giving up on this request")
                query = None

            if not query:
                state_manager.set_state(AssistantState.SPEAKING)
                interrupted = self._speak_safely(tts, not_understood(response_language), response_language)
                return None, interrupted

        target = media_youtube.build_search_url(query)
        return Command(name=command.name, params={**command.params, "target": target}), False

    def _resolve_schedule_event(
        self, command: Command, command_stt: SpeechToText, tts: TextToSpeech, response_language: str
    ) -> tuple[Command | None, bool]:
        """Called for a "schedule_event" command before it's dispatched (see
        core/voice/intent.py's _SCHEDULE_PATTERNS): asks the user for
        details if they gave none ("напомни мне" with nothing else), then
        turns the raw text into a structured title/event_time/
        remind_before_minutes via modules.calendar.extraction (AI, since a
        rule-based parser can't reliably turn "в пятницу"/"через час" into
        a real date). On success, rewrites this into a plain
        "calendar_create_event" command — the actual calendar module
        (modules/calendar/) never needs to know this voice shortcut exists.

        Returns (None, interrupted) if the clarifying question got
        barge-in-cut off, or if nothing usable came back at all (empty
        answer, every extraction adapter failed, or the model couldn't make
        sense of the request) — there's no raw-text fallback that makes
        sense for calendar_create_event (it requires a real title and a
        real ISO-8601 event_time), so giving up and saying "not understood"
        is the only sane option left."""
        raw_text = command.params.get("raw_text", "").strip()

        if not raw_text:
            state_manager.set_state(AssistantState.SPEAKING)
            if self._speak_safely(tts, "Что и на какое время записать?", response_language):
                return None, True

            state_manager.set_state(AssistantState.LISTENING, "Жду детали")
            details_audio = audio_io.record_until_silence(self._settings, self._stop_event)
            raw_text = command_stt.transcribe(details_audio).text.strip()
            if not raw_text:
                return None, False

        try:
            extracted = run_cancellable(
                calendar_extraction.extract_event(raw_text), self._barge_in, response_language
            )
        except TurnCancelled:
            raise
        except Exception:
            logger.exception("Event extraction failed; giving up on this request")
            extracted = None

        if extracted is None:
            state_manager.set_state(AssistantState.SPEAKING)
            interrupted = self._speak_safely(tts, not_understood(response_language), response_language)
            return None, interrupted

        params = {
            "title": extracted.title,
            "event_time": extracted.event_time.isoformat(),
            "remind_before_minutes": str(extracted.remind_before_minutes),
        }
        return Command(name="calendar_create_event", params=params), False

    def _resolve_ui_action(
        self, command: Command, tts: TextToSpeech, response_language: str
    ) -> tuple[Command | None, bool]:
        """Called for a "ui_action" command before it's dispatched (see
        core/voice/intent.py's _UI_ACTION_PATTERNS, and
        modules/ui_automation/handlers.py's registered "ui_action" command,
        which is what lets classify() also produce this from unpatterned
        phrasing). Grounds the raw instruction against whatever application
        currently has OS focus (modules.ui_automation.service_layer.
        ground_instruction) and, if that produced a usable action plan,
        speaks it out loud BEFORE dispatching — this is the "speak first,
        then act" safety behavior: any actual click/type_text/press_key
        call never runs until after the announcement has finished playing.

        Like _resolve_messaging_reply, this never hands a plain Command
        back for _handle_command's generic dispatch call to run — it
        dispatches (and confirms) the action itself, right here, after the
        announcement above. ui_action is registered dangerous=True (see
        modules/ui_automation/handlers.py's design notes: a raw
        /api/command call bypasses this resolver entirely, and unlike a
        Telegram reply, a click/keystroke/typed-text sequence run with zero
        confirmation from an unauthenticated LAN request is full remote
        control of this machine's mouse/keyboard) — but the GENERIC
        dangerous-command confirmation flow in _handle_command would ask a
        second, content-free "Требуется подтверждение?" and then block on
        a spoken yes/no, exactly the blocking prompt the user asked NOT to
        have here (announce-then-act, not a gate). So the spoken
        announcement above *is* the real confirmation, and once it's
        finished playing uninterrupted, this immediately calls dispatch()
        then confirm() itself with no second prompt.

        Always returns (None, interrupted): an ordinary "не поняла
        команду" is spoken if grounding found nothing usable at all (no
        active window, no AT-SPI elements, or the grounding model couldn't
        confidently match anything); if the announcement itself gets
        barge-in-cut off mid-sentence, the action is deliberately
        abandoned rather than executed anyway — the user interrupted
        before hearing what was about to happen, so it doesn't happen."""
        raw_text = command.params.get("raw_text", "").strip()
        steps = None
        if raw_text:
            try:
                steps = run_cancellable(
                    ui_service_layer.ground_instruction(raw_text), self._barge_in, response_language
                )
            except TurnCancelled:
                raise
            except Exception:
                logger.exception("UI action grounding failed")
                steps = None

        if not steps:
            state_manager.set_state(AssistantState.SPEAKING)
            interrupted = self._speak_safely(tts, not_understood(response_language), response_language)
            return None, interrupted

        announcement = ui_announce.describe_steps(steps, response_language)
        state_manager.set_state(AssistantState.SPEAKING)
        if self._speak_safely(tts, announcement, response_language):
            return None, True

        params = {"steps": ui_service_layer.to_command_params(steps), "announcement": announcement}
        response = run_cancellable(
            self._dispatcher.dispatch(command.name, params), self._barge_in, response_language
        )
        if response.status == CommandStatus.CONFIRMATION_REQUIRED and response.token:
            response = run_cancellable(
                self._dispatcher.confirm(response.token, True), self._barge_in, response_language
            )

        state_manager.set_state(AssistantState.SPEAKING)
        interrupted = self._speak_safely(tts, localize_response(response, response_language), response_language)
        return None, interrupted

    def _resolve_task_plan(
        self, command: Command, tts: TextToSpeech, response_language: str
    ) -> tuple[Command | None, bool]:
        """Called for a "run_task_plan" command before it's dispatched (see
        modules/task_orchestrator/handlers.py's registered "run_task_plan"
        command — produced by classify() from a composite/multi-step
        instruction that named no single matching command on its own).
        Builds a plan of real dispatcher commands
        (modules.task_orchestrator.service_layer.build_plan) and, if that
        produced a usable plan, speaks it out loud BEFORE dispatching —
        same "speak first, then act" safety behavior as
        _resolve_ui_action, and for the identical reason: an
        already-announced plan doesn't need a second yes/no prompt per
        step, so modules/task_orchestrator/handlers.py's executor
        auto-confirms every step itself once this dispatches
        "run_task_plan".

        Like _resolve_ui_action, this never hands a plain Command back for
        _handle_command's generic dispatch call to run — it dispatches
        (and confirms) the plan itself, right here, after the announcement
        above.

        Always returns (None, interrupted): an ordinary "не поняла
        команду" is spoken if planning found nothing usable at all (no
        commands fit the request, or the planning model couldn't
        confidently produce a valid sequence); if the announcement itself
        gets barge-in-cut off mid-sentence, the plan is deliberately
        abandoned rather than executed anyway — same reasoning as
        _resolve_ui_action."""
        raw_text = command.params.get("raw_text", "").strip()
        task_plan = None
        if raw_text:
            try:
                task_plan = run_cancellable(
                    task_orchestrator_service_layer.build_plan(raw_text, self._dispatcher),
                    self._barge_in,
                    response_language,
                )
            except TurnCancelled:
                raise
            except Exception:
                logger.exception("Task plan building failed")
                task_plan = None

        if not task_plan or not task_plan.steps:
            state_manager.set_state(AssistantState.SPEAKING)
            interrupted = self._speak_safely(tts, not_understood(response_language), response_language)
            return None, interrupted

        announcement = task_orchestrator_announce.describe_plan(task_plan, response_language)
        state_manager.set_state(AssistantState.SPEAKING)
        if self._speak_safely(tts, announcement, response_language):
            return None, True

        params = {
            "steps": [{"command": step.command, "params": step.params} for step in task_plan.steps],
            "announcement": announcement,
        }
        response = run_cancellable(
            self._dispatcher.dispatch(command.name, params), self._barge_in, response_language
        )
        if response.status == CommandStatus.CONFIRMATION_REQUIRED and response.token:
            response = run_cancellable(
                self._dispatcher.confirm(response.token, True), self._barge_in, response_language
            )

        state_manager.set_state(AssistantState.SPEAKING)
        interrupted = self._speak_safely(tts, localize_response(response, response_language), response_language)
        return None, interrupted

    def _resolve_board_game(
        self, command: Command, tts: TextToSpeech, command_stt: SpeechToText, response_language: str
    ) -> tuple[Command | None, bool]:
        """Called for a "start_board_game" command (see
        core/voice/intent.py's _BOARD_GAME_PHRASES — rule-only; unlike
        every other command this file resolves, there's no dispatcher
        command backing this one for the AI classifier to fall back to,
        since there's nothing to *dispatch* — the whole game runs
        synchronously right here). Plays a full game of chess or Russian
        draughts against the user.

        This is the one genuinely unbounded turn loop in this file — every
        other _resolve_* method is a single fixed exchange (see
        modules/board_games/service_layer.py's GameSession docstring for
        why an ordinary local variable is enough state for it). The engine
        subprocess (chess only — see modules.board_games.chess_adapter)
        must always be released once the game ends, however it ends —
        normal game-over, resignation, a stop phrase, or a barge-in
        TurnCancelled bubbling up mid-move — hence the try/finally rather
        than relying on the happy path to reach the cleanup call.

        Always returns (None, interrupted): like _resolve_ui_action/
        _resolve_task_plan, nothing is left for _handle_command's generic
        dispatch call to do afterward."""
        game_param = command.params.get("game", "")
        if game_param not in ("chess", "checkers"):
            state_manager.set_state(AssistantState.SPEAKING)
            if self._speak_safely(tts, board_games_announce.which_game_prompt(), response_language):
                return None, True

            state_manager.set_state(AssistantState.LISTENING, "Жду ответа")
            answer_audio = audio_io.record_until_silence(self._settings, self._stop_event)
            answer_text = command_stt.transcribe(answer_audio).text.strip().lower()
            if "шашк" in answer_text:
                game_param = "checkers"
            elif "шахмат" in answer_text:
                game_param = "chess"
            else:
                state_manager.set_state(AssistantState.SPEAKING)
                interrupted = self._speak_safely(tts, not_understood(response_language), response_language)
                return None, interrupted

        kind = GameKind(game_param)
        session = board_games_service_layer.start_game(kind)

        state_manager.set_state(AssistantState.SPEAKING)
        if self._speak_safely(tts, board_games_announce.game_started_text(kind), response_language):
            board_games_service_layer.finish(session)
            return None, True

        try:
            interrupted = self._run_board_game_loop(session, tts, command_stt, response_language)
        finally:
            summary = board_games_service_layer.finish(session)

        state_manager.request_image(summary.board_svg)

        lines = [
            board_games_announce.result_text(summary.result_string),
            board_games_announce.summary_intro_text(len(summary.mistakes)),
        ]
        lines.extend(board_games_announce.mistake_text(m) for m in summary.mistakes)
        state_manager.set_state(AssistantState.SPEAKING)
        interrupted = self._speak_safely(tts, " ".join(lines), response_language) or interrupted
        return None, interrupted

    def _run_board_game_loop(
        self,
        session: board_games_service_layer.GameSession,
        tts: TextToSpeech,
        command_stt: SpeechToText,
        response_language: str,
    ) -> bool:
        """The turn-by-turn loop behind _resolve_board_game, split out only
        so that method's own try/finally (engine cleanup) reads cleanly.
        Returns True if a spoken reply got barge-in-cut off mid-sentence —
        a TurnCancelled raised while resolving/applying a move propagates
        straight through instead (same as every other resolver in this
        file); the caller's finally block still releases the engine."""
        while not board_games_service_layer.is_over(session):
            state_manager.set_state(AssistantState.LISTENING, "Жду ваш ход")
            move_audio = audio_io.record_until_silence(self._settings, self._stop_event)
            move_text = command_stt.transcribe(move_audio).text.strip()
            if not move_text:
                continue
            if is_stop_command(move_text, response_language) or is_resign_command(move_text, response_language):
                return False

            matched = run_cancellable(
                board_games_service_layer.resolve_player_move(session, move_text),
                self._barge_in,
                response_language,
            )
            if matched is None:
                state_manager.set_state(AssistantState.SPEAKING)
                if self._speak_safely(tts, board_games_announce.move_not_understood_text(), response_language):
                    return True
                continue

            board_games_service_layer.apply_player_move(session, matched)
            if board_games_service_layer.is_over(session):
                break

            engine_move = board_games_service_layer.apply_engine_move(session)
            speak_parts = [f"Вы сыграли {matched}.", board_games_announce.engine_move_text(engine_move)]
            if board_games_service_layer.is_check(session):
                speak_parts.append(board_games_announce.check_text())
            state_manager.set_state(AssistantState.SPEAKING)
            if self._speak_safely(tts, " ".join(speak_parts), response_language):
                return True

        return False

    def _resolve_pending_message_target(
        self, raw_target: str, tts: TextToSpeech, command_stt: SpeechToText, response_language: str
    ) -> tuple[PendingMessage | None, bool]:
        """Shared by _resolve_messaging_reply/_resolve_messaging_snooze:
        figures out which pending watched-contact message a "ответь"/
        "отложи" command refers to.

        With exactly one message pending, that one is used directly
        regardless of what (if anything) `raw_target` says — there's only
        one candidate to begin with, so a name comparison couldn't actually
        disambiguate anything. This is deliberately not gated on
        `raw_target` matching it: _resolve_messaging_snooze passes its whole
        captured remainder here (e.g. "иру на 10 минут" — duration and all,
        not just a name; see that method), so requiring a name-shaped match
        would misfire on a bare "отложи на 10 минут" with no name in it at
        all. For _resolve_messaging_reply specifically, a wrong guess here
        is still caught downstream: that resolver reads the target's name
        back ("Ира: '...'. Отправить?") before ever sending anything, so
        the user gets a chance to notice and decline.

        With more than one message pending, `raw_target` must fuzzy-match
        exactly one sender to be used directly without asking anything —
        same fuzzy-matching primitive already used for stop-word/wake-word/
        confirmation recognition (core.voice.phrase_matching), applied here
        to "spoken name vs. a pending message's sender_label" instead.
        Otherwise (no name given, or the match is ambiguous/not found) asks
        "от кого?" and matches the spoken answer the same way.

        Returns (None, False) with "нет ожидающих сообщений" spoken if
        nothing is pending at all, or (None, True) if the "от кого?"
        question itself got barge-in-cut off mid-sentence."""
        pending = messaging_service_layer.list_pending(MessagingUnitOfWork())
        if not pending:
            state_manager.set_state(AssistantState.SPEAKING)
            self._speak_safely(tts, "Нет ожидающих сообщений.", response_language)
            return None, False

        if len(pending) == 1:
            return pending[0], False

        def _match(text: str) -> list[PendingMessage]:
            text = text.strip()
            if not text:
                return []
            return [message for message in pending if fuzzy_contains_phrase(text, message.sender_label)]

        candidates = _match(raw_target)
        if len(candidates) == 1:
            return candidates[0], False

        names = ", ".join(message.sender_label for message in pending)
        state_manager.set_state(AssistantState.SPEAKING)
        if self._speak_safely(tts, f"От кого — {names}?", response_language):
            return None, True

        state_manager.set_state(AssistantState.LISTENING, "Жду ответа")
        answer_audio = audio_io.record_until_silence(self._settings, self._stop_event)
        answer_text = command_stt.transcribe(answer_audio).text.strip()
        if not answer_text:
            return None, False

        candidates = _match(answer_text)
        if len(candidates) == 1:
            return candidates[0], False

        state_manager.set_state(AssistantState.SPEAKING)
        interrupted = self._speak_safely(tts, not_understood(response_language), response_language)
        return None, interrupted

    def _resolve_messaging_reply(
        self,
        command: Command,
        command_stt: SpeechToText,
        tts: TextToSpeech,
        response_language: str,
        spoken_language: str,
    ) -> tuple[Command | None, bool]:
        """Called for a "messaging_reply" command before it's dispatched
        (see core/voice/intent.py's _MESSAGING_REPLY_PATTERNS). Unlike
        every other resolver in this file, this one never hands a plain
        Command back for _handle_command's generic dispatch call to run —
        it dispatches (and confirms) the send itself, right here, after
        its OWN content-specific "Ире: '...'. Отправить?" yes/no. This is
        deliberate: messaging_reply is registered dangerous=True (see
        modules/messaging/handlers.py's design notes — a raw /api/command
        call bypasses this resolver entirely, so the dispatcher-level gate
        is the only thing protecting against a zero-confirmation send from
        that path), but the GENERIC dangerous-command confirmation flow in
        _handle_command only ever speaks a content-free "Требуется
        подтверждение" — it can't read back what's actually about to be
        sent. So this resolver's own yes/no *is* the real confirmation,
        and once given, it immediately calls dispatch() then confirm()
        itself with no second, redundant prompt.

        Always returns (None, interrupted) — there's nothing left for
        _handle_command to do afterward regardless of outcome."""
        raw_target = command.params.get("raw_target", "")
        target, interrupted = self._resolve_pending_message_target(
            raw_target, tts, command_stt, response_language
        )
        if target is None:
            return None, interrupted

        state_manager.set_state(AssistantState.SPEAKING)
        if self._speak_safely(tts, "Что ответить?", response_language):
            return None, True

        state_manager.set_state(AssistantState.LISTENING, "Слушаю ответ")
        reply_audio = audio_io.record_until_silence(self._settings, self._stop_event)
        raw_reply = command_stt.transcribe(reply_audio).text.strip()
        if not raw_reply:
            return None, False

        try:
            cleaned = run_cancellable(
                messaging_text_cleanup.clean_dictated_text(raw_reply), self._barge_in, response_language
            )
        except TurnCancelled:
            raise
        except Exception:
            logger.exception("Dictated reply cleanup failed; using the raw transcription")
            cleaned = raw_reply

        state_manager.set_state(AssistantState.SPEAKING)
        if self._speak_safely(tts, f"{target.sender_label}: «{cleaned}». Отправить?", response_language):
            return None, True

        state_manager.set_state(AssistantState.LISTENING, "Жду подтверждения")
        confirm_audio = audio_io.record_until_silence(self._settings, self._stop_event)
        confirm_result = command_stt.transcribe(confirm_audio)
        if not is_affirmative(confirm_result.text, spoken_language):
            state_manager.set_state(AssistantState.SPEAKING)
            interrupted = self._speak_safely(tts, "Хорошо, не отправляю.", response_language)
            return None, interrupted

        response = run_cancellable(
            self._dispatcher.dispatch(
                command.name,
                {
                    "message_id": target.id,
                    "text": cleaned,
                    # Lets _handle_reply detect a new message merging into
                    # this same row while this multi-turn confirmation was
                    # in progress (see modules/messaging/handlers.py) —
                    # without it, that arrival would get silently marked
                    # REPLIED along with the original.
                    "expected_received_at": target.received_at.isoformat() if target.received_at else None,
                },
            ),
            self._barge_in,
            response_language,
        )
        if response.status == CommandStatus.CONFIRMATION_REQUIRED and response.token:
            response = run_cancellable(
                self._dispatcher.confirm(response.token, True), self._barge_in, response_language
            )

        state_manager.set_state(AssistantState.SPEAKING)
        interrupted = self._speak_safely(tts, localize_response(response, response_language), response_language)
        return None, interrupted

    def _resolve_messaging_snooze(
        self, command: Command, command_stt: SpeechToText, tts: TextToSpeech, response_language: str
    ) -> tuple[Command | None, bool]:
        """Called for a "messaging_snooze" command before it's dispatched
        (see core/voice/intent.py's _MESSAGING_SNOOZE_PATTERNS). Finds the
        target message the same way _resolve_messaging_reply does, then
        tries to parse a duration out of the raw captured text (e.g.
        "отложи Иру на 10 минут") without asking anything; only asks "на
        сколько отложить?" if that came up empty. Gives up with "не
        поняла" if the follow-up answer still doesn't parse — no AI
        escalation, see modules/messaging/duration.py's own reasoning for
        why a second, smarter attempt isn't warranted here."""
        raw_text = command.params.get("raw_text", "")
        target, interrupted = self._resolve_pending_message_target(
            raw_text, tts, command_stt, response_language
        )
        if target is None:
            return None, interrupted

        minutes = parse_duration_minutes(raw_text)
        if minutes is None:
            state_manager.set_state(AssistantState.SPEAKING)
            if self._speak_safely(tts, "На сколько отложить?", response_language):
                return None, True

            state_manager.set_state(AssistantState.LISTENING, "Жду ответа")
            duration_audio = audio_io.record_until_silence(self._settings, self._stop_event)
            duration_text = command_stt.transcribe(duration_audio).text.strip()
            minutes = parse_duration_minutes(duration_text) if duration_text else None

        if minutes is None:
            state_manager.set_state(AssistantState.SPEAKING)
            interrupted = self._speak_safely(tts, not_understood(response_language), response_language)
            return None, interrupted

        return Command(name=command.name, params={"message_id": target.id, "minutes": minutes}), False

    def _resolve_messaging_watch_contact(
        self, command: Command, tts: TextToSpeech, response_language: str
    ) -> tuple[Command | None, bool]:
        """Called for a "messaging_watch_contact" command before it's
        dispatched (see core/voice/intent.py's _MESSAGING_WATCH_PATTERNS).
        No AI, no follow-up question — deliberately literal (see
        modules/messaging/service_layer.py's design notes): strips a
        trailing "в телеграме"/"на почте" and uses whatever's left as-is
        as the identifier. Whichever suffix pattern actually stripped
        something decides the source; a neutral phrase where neither
        matches falls back to "telegram", unchanged from before Gmail
        existed as a source. Only ever fails if nothing at all is left to
        use, which just gives up with "не поняла" rather than asking again."""
        raw_text = command.params.get("raw_text", "").strip()
        without_gmail = _GMAIL_SUFFIX_PATTERN.sub("", raw_text).strip()
        if without_gmail != raw_text:
            source, identifier = "gmail", without_gmail
        else:
            source, identifier = "telegram", _TELEGRAM_SUFFIX_PATTERN.sub("", raw_text).strip()
        if not identifier:
            state_manager.set_state(AssistantState.SPEAKING)
            interrupted = self._speak_safely(tts, not_understood(response_language), response_language)
            return None, interrupted
        return Command(name=command.name, params={"source": source, "identifier": identifier}), False

    @staticmethod
    def _learn_facts(text: str, language: str) -> None:
        """Best-effort ongoing memory: rule-based extraction (see
        core/voice/fact_extraction.py) on every command utterance, stored as
        episodic facts that get evicted over time unless reinforced — never
        allowed to break the actual command handling if it fails."""
        try:
            for fact in extract_facts(text, language):
                profile_service_layer.record_episodic_fact(ProfileUnitOfWork(), fact.key, fact.value)
        except Exception:
            logger.exception("Fact extraction failed for utterance")

    def _handle_command(self, command_stt: SpeechToText, tts: TextToSpeech) -> bool:
        """Returns True if the user barge-in-interrupted the spoken reply
        with a stop phrase — see VoiceAssistantLoop._run, which then skips
        the wake-word wait for the next turn."""
        state_manager.set_state(AssistantState.LISTENING, "Слушаю команду")
        audio = audio_io.record_until_silence(self._settings, self._stop_event)
        if audio.size == 0:
            state_manager.set_state(AssistantState.IDLE)
            return False

        state_manager.set_state(AssistantState.PROCESSING, "Распознаю")
        result = command_stt.transcribe(audio)
        decision = resolve_language(result.detected_language, result.language_probability, self._settings)
        # decision.resolved drives interpretation of the user's own words (interpret,
        # is_affirmative); response_language drives what the assistant speaks back and
        # may differ from it when response_language_override is configured.
        response_language = resolve_response_language(decision.resolved, self._settings)

        self._learn_facts(result.text, decision.resolved)

        command = interpret(result.text, decision.resolved)
        if command is not None and command.name in ("messaging_reply", "messaging_snooze"):
            # "ответь"/"отложи" are common phrase-openers for plenty of non-
            # messaging requests too ("ответь, который час", "отложи это на
            # потом" as a throwaway remark) — _MESSAGING_REPLY_PATTERNS/
            # _MESSAGING_SNOOZE_PATTERNS in intent.py match on the verb
            # alone, with no way to check for an actual pending message from
            # a regex. Only claim the utterance as one of these commands
            # when there's really something to act on; otherwise treat it
            # exactly as if interpret() hadn't matched at all, so it still
            # gets a chance at plugin matching / a real AI answer instead of
            # a flat "Нет ожидающих сообщений." dead end.
            if not messaging_service_layer.list_pending(MessagingUnitOfWork()):
                command = None
        if command is None:
            command = match_plugin_command(result.text)
        if command is None:
            command, interrupted = self._classify_via_ai_bridge(result.text, command_stt, tts, response_language)
            if command is None:
                state_manager.set_state(AssistantState.IDLE)
                return interrupted

        try:
            if command.name == "open_app":
                command, interrupted = self._resolve_open_app_target(
                    command, command_stt, tts, response_language, decision.resolved
                )
                if command is None:
                    state_manager.set_state(AssistantState.IDLE)
                    return interrupted
            elif command.name == "open_media":
                command, interrupted = self._resolve_media_target(command, command_stt, tts, response_language)
                if command is None:
                    state_manager.set_state(AssistantState.IDLE)
                    return interrupted
            elif command.name == "schedule_event":
                command, interrupted = self._resolve_schedule_event(command, command_stt, tts, response_language)
                if command is None:
                    state_manager.set_state(AssistantState.IDLE)
                    return interrupted
            elif command.name == "ui_action":
                command, interrupted = self._resolve_ui_action(command, tts, response_language)
                if command is None:
                    state_manager.set_state(AssistantState.IDLE)
                    return interrupted
            elif command.name == "run_task_plan":
                command, interrupted = self._resolve_task_plan(command, tts, response_language)
                if command is None:
                    state_manager.set_state(AssistantState.IDLE)
                    return interrupted
            elif command.name == "start_board_game":
                command, interrupted = self._resolve_board_game(command, tts, command_stt, response_language)
                if command is None:
                    state_manager.set_state(AssistantState.IDLE)
                    return interrupted
            elif command.name == "messaging_watch_contact":
                command, interrupted = self._resolve_messaging_watch_contact(command, tts, response_language)
                if command is None:
                    state_manager.set_state(AssistantState.IDLE)
                    return interrupted
            elif command.name == "messaging_snooze":
                command, interrupted = self._resolve_messaging_snooze(
                    command, command_stt, tts, response_language
                )
                if command is None:
                    state_manager.set_state(AssistantState.IDLE)
                    return interrupted
            elif command.name == "messaging_reply":
                # Unlike every other branch here, this resolver always
                # returns (None, ...) — it dispatches (and, since
                # messaging_reply is dangerous=True, confirms) the send
                # itself, entirely inside _resolve_messaging_reply, rather
                # than handing a Command back for the generic dispatch call
                # below to run. See that method's docstring for why.
                _, interrupted = self._resolve_messaging_reply(
                    command, command_stt, tts, response_language, decision.resolved
                )
                state_manager.set_state(AssistantState.IDLE)
                return interrupted

            response = run_cancellable(
                self._dispatcher.dispatch(command.name, command.params), self._barge_in, response_language
            )

            if response.status == CommandStatus.CONFIRMATION_REQUIRED and response.token:
                # Unlike every other _speak_safely call in this file, a barge-in
                # interruption here must NOT bail out early: dispatch() has
                # already created a live pending token that needs resolving one
                # way or another, and the interruption itself carries no
                # yes/no answer (BargeInMonitor only recognizes STOP_PHRASES,
                # e.g. "отмена" - a real decline - not "да"). Bailing used to
                # silently abandon the token and let the next loop iteration
                # treat whatever the user said next as a brand new top-level
                # command instead of the answer to this question - the exact
                # "да воспринимается как ещё один запрос" symptom this fixes.
                state_manager.set_state(AssistantState.SPEAKING)
                self._speak_safely(tts, localize_response(response, response_language), response_language)

                state_manager.set_state(AssistantState.LISTENING, "Жду подтверждения")
                confirm_audio = audio_io.record_until_silence(self._settings, self._stop_event)
                confirm_result = command_stt.transcribe(confirm_audio)
                approved = is_affirmative(confirm_result.text, decision.resolved)

                state_manager.set_state(AssistantState.PROCESSING)
                response = run_cancellable(
                    self._dispatcher.confirm(response.token, approved), self._barge_in, response_language
                )
        except TurnCancelled:
            # A stop phrase was heard while a resolve step or dispatch()
            # itself (the actual command execution — clicks, keystrokes,
            # launching an app, ...) was still running. Mirrors how a
            # barge-in interruption during speech already behaves: stop
            # silently, no "остановлено" acknowledgment, and listen again
            # immediately rather than requiring the wake word again.
            state_manager.set_state(AssistantState.IDLE)
            return True

        state_manager.set_state(AssistantState.SPEAKING)
        interrupted = self._speak_safely(tts, localize_response(response, response_language), response_language)
        state_manager.set_state(AssistantState.IDLE)
        return interrupted
