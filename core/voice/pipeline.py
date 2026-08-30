from __future__ import annotations

import asyncio
import re
import threading

import numpy as np

from core.dispatcher import CommandDispatcher
from core.logger import get_logger
from core.models import AssistantState, CommandResponse, CommandStatus
from core.state import state_manager
from core.voice import ai_router, audio_io, confirmation_phrase, special_phrases, wake_word
from core.voice.barge_in import BargeInMonitor
from core.voice.config import VoiceSettings, voice_settings
from core.voice.intent import (
    Command,
    interpret,
    is_affirmative,
    is_fitness_exit_command,
    is_resign_command,
    is_stop_command,
)
from core.voice.interruption import TurnCancelled, run_cancellable
from core.voice.language import LanguageDecision, resolve_language, resolve_response_language
from core.voice.phrase_matching import fuzzy_contains_phrase, fuzzy_matches_any, with_transliterated_variant
from core.voice.plugin_match import match_plugin_command
from core.voice.fact_extraction import extract_facts
from core.voice.responses import localize_response, not_understood, tray_hide_ack, tray_show_ack
from core.voice.stt import SpeechToText
from core.voice.tts import TextToSpeech
from modules import multi_command_parser
from modules.app_catalog import resolver as app_resolver
from modules.board_games import announce as board_games_announce
from modules.board_games import service_layer as board_games_service_layer
from modules.board_games import ui_session as board_games_ui_session
from modules.board_games.domain import GameKind
from modules.calendar import extraction as calendar_extraction
from modules.conversation_log import record_assistant, record_user
from modules.custom_commands import dispatcher as custom_commands
from modules.custom_commands.domain import ActionType, CustomCommand
from modules.delayed_execution import command_parser as delayed_command_parser
from modules.delayed_execution import resolver as delayed_resolver
from modules.delayed_execution import service_layer as delayed_service_layer
from modules.delayed_execution.uow import DelayedExecutionUnitOfWork
from modules.fitness_tracker import announce as fitness_announce
from modules.fitness_tracker import context_state as fitness_context_state
from modules.fitness_tracker import fitness_chat
from modules.fitness_tracker import intent_parser as fitness_intent_parser
from modules.fitness_tracker import voice_commands as fitness_voice_commands
from modules.fitness_tracker.intent_parser import ParsedIntent
from modules.hardware_adaptive import command_classifier
from modules.media import query_correction as media_query_correction
from modules.media import recommender as media_recommender
from modules.media import youtube as media_youtube
from modules.messaging import service_layer as messaging_service_layer
from modules.messaging import text_cleanup as messaging_text_cleanup
from modules.messaging.domain import PendingMessage
from modules.messaging.duration import parse_duration_minutes
from modules.messaging.uow import MessagingUnitOfWork
from modules.os_agent import announce as os_agent_announce
from modules.os_agent import planner as os_agent_planner
from modules.os_agent import runner as os_agent_runner
from modules.os_agent import session as os_agent_session
from modules.os_agent.domain import AgentSession
from modules.task_orchestrator import announce as task_orchestrator_announce
from modules.task_orchestrator import service_layer as task_orchestrator_service_layer
from modules.ui_automation import announce as ui_announce
from modules.ui_automation import service_layer as ui_service_layer
from modules.ui_automation.domain import UIStep
from modules.ui_control import service_layer as ui_control_service_layer
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

# Keyed by PromptProviderPort.name (see core/ai_adapter_chain.py:candidate_chain
# and its adapters) — surfaced via ai_router.resolve_free_text's on_progress in
# _classify_via_ai_bridge below, so a slow chain (local model down, browser
# fallback) shows something other than a static "Уточняю у ИИ" the whole time.
# Any name not listed here (there isn't one currently) falls back to that
# same default text rather than a KeyError.
_AI_ADAPTER_PROGRESS_DETAIL = {
    "local": "Пробую локальную модель",
    "groq_api": "Пробую быстрый облачный ИИ",
    "gemini_api": "Пробую Gemini",
    "claude_api": "Пробую Claude",
    "ai_bridge": "Локально не получилось, открываю браузер",
}


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
            logger.exception("TTS failed: %s", exc)
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
        # Separate from both events above: set by request_manual_wake() to
        # let something outside this thread (the Electron "Начать разговор"
        # button, via /api/voice/trigger) emulate hearing the wake phrase
        # without a stop_event-style full loop teardown. Checked by
        # _wait_for_wake_or_pause as an extra_stop_event passed into
        # wake_word.listen_for_phrases, so it interrupts a blocking listen
        # call rather than only being noticed on the next pass.
        self._manual_trigger_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._barge_in = BargeInMonitor(settings)
        # One-line summary of the previous exchange within the current
        # continuous-conversation activation (see _run()) — lets an
        # elliptical follow-up ("а сегодня какая была?" with no "погода" at
        # all) resolve against the same topic/params as the turn before it
        # instead of every utterance being classified in total isolation.
        # Set at _handle_command's single choke point for a dispatched
        # command, or in _classify_via_ai_bridge for a direct answer; reset
        # to None at the start of each fresh activation in _run() so it
        # never leaks into an unrelated later conversation.
        self._last_exchange: str | None = None

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

    def request_manual_wake(self) -> bool:
        """Emulates hearing the wake phrase, for a UI trigger that isn't a
        spoken phrase (see /api/voice/trigger — the Electron "Начать
        разговор" button, routed through this same loop/mic instead of
        opening a second microphone in the browser). Returns False without
        effect if the loop isn't running.

        Clears _paused_event itself (rather than leaving that to
        _wait_for_wake_or_pause) before setting _manual_trigger_event, so
        the single check that consumes the trigger there (see that
        method's docstring) can tell "genuinely start a turn" apart from
        request_pause()'s own use of the same event purely to interrupt a
        blocking listen — by the time it's consumed, _paused_event already
        reflects which one actually happened."""
        if not self.is_running:
            return False
        self._paused_event.clear()
        self._manual_trigger_event.set()
        return True

    def request_pause(self) -> bool:
        """Emulates hearing the configured stop word — pauses this loop the
        same way _wait_for_wake_or_pause's own "pause" branch does, without
        tearing the thread down like stop() does. Used by /api/voice/pause
        (the Electron "Завершить разговор" button) so ending a
        button-driven conversation doesn't kill the always-on assistant.
        Returns False without effect if the loop isn't running.

        Also sets _manual_trigger_event, purely to interrupt whatever
        listen_for_phrases call is currently blocking (see
        _wait_for_wake_or_pause) — found live: without this, setting
        _paused_event alone had no real effect until that blocking call
        happened to return on its own (hearing wake/pause/tray/resume),
        which could be indefinitely far in the future. The status display
        updated immediately (misleadingly implying it had worked) while the
        loop itself kept right on listening for the wake word as if nothing
        had changed — the button read as "does nothing the first time" and
        the stop word then had to be said twice to actually resume anything
        (once to make the stale pause finally register, once more to
        genuinely resume)."""
        if not self.is_running:
            return False
        self._paused_event.set()
        state_manager.set_state(AssistantState.PAUSED, "Скажите стоп-слово ещё раз, чтобы продолжить")
        self._manual_trigger_event.set()
        return True

    def _speak_safely(self, tts: TextToSpeech, text: str, language: str) -> bool:
        """Speaks `text`. Returns True if the user's stop word cut it off
        partway through (see BargeInMonitor) — the caller should treat that
        exactly like any other barge-in interruption: propagate it up as
        `interrupted` until it reaches VoiceAssistantLoop._run, which pauses
        (AssistantState.PAUSED), not "go straight back to listening"."""
        # Recorded here, before synthesis, so the on-screen transcript
        # still shows what the assistant meant to say even if TTS or the
        # speaker fails below. Every spoken command result, prompt and
        # acknowledgement in this loop passes through _speak_safely; the
        # streamed free-text answers that don't are recorded in
        # _classify_via_ai_bridge instead.
        if text and text.strip():
            record_assistant(text, "voice")
        try:
            samples, sample_rate = tts.synthesize(text, language)
        except RuntimeError as exc:
            logger.exception("TTS failed: %s", exc)
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

    def _record_command_audio(self, *, onset_timeout_seconds: float | None = None) -> tuple[np.ndarray, bool]:
        """Records the same way audio_io.record_until_silence always has,
        except a BargeInMonitor listens on a second mic stream at the same
        time for the user's own configured stop word (context="recording" —
        see core/voice/special_phrases.py) — saying it while still
        mid-utterance now cuts the recording short right away, instead of
        only being caught after VAD silence ends it naturally and
        _handle_command's own post-transcription text check runs. Mirrors
        _speak_safely's bracket exactly (fresh stop_event/interrupted pair,
        a dedicated monitor thread torn down in `finally`), just around a
        capture instead of playback.

        Best-effort: BargeInMonitor.run already degrades silently (logs at
        DEBUG, never sets `interrupted`) if the audio backend can't actually
        open a second concurrent input stream alongside the one
        record_until_silence itself holds — this never fails the turn, it
        just means no live interruption for that one recording, same as
        before this existed.

        Returns (audio, interrupted) — `audio` is whatever was captured
        before an interruption, if any (the caller should discard it, not
        transcribe/dispatch it, when `interrupted` is True — same contract
        as every other barge-in interruption in this file)."""
        stop_event = threading.Event()
        interrupted = threading.Event()
        monitor_thread = threading.Thread(
            target=self._barge_in.run,
            args=(self._settings.fallback_language, stop_event, interrupted),
            kwargs={"context": "recording"},
            daemon=True,
        )
        monitor_thread.start()
        try:
            audio = audio_io.record_until_silence(
                self._settings,
                self._stop_event,
                onset_timeout_seconds=onset_timeout_seconds,
                barge_in_stop_event=stop_event,
            )
        finally:
            stop_event.set()
            monitor_thread.join(timeout=1.0)
        return audio, interrupted.is_set()

    def _run_onboarding_if_needed(self) -> None:
        if profile_service_layer.is_onboarded(ProfileUnitOfWork()):
            return
        state_manager.set_state(AssistantState.ONBOARDING, "Знакомство")
        try:
            run_onboarding(self._settings, self._stop_event)
        except Exception:
            logger.exception("Onboarding failed")
        state_manager.set_state(AssistantState.IDLE)

    def _ack_language(self) -> str:
        return self._settings.response_language_override or self._settings.fallback_language

    def _wait_for_wake_or_pause(self, tts: TextToSpeech) -> bool:
        """Blocks until the wake word is heard (returns True, caller should
        proceed to _handle_command) or the whole loop should stop (returns
        False — self._stop_event fired).

        self._manual_trigger_event is passed into every listen_for_phrases
        call as extra_stop_event, so it cuts a blocking listen short the
        same way the wake phrase itself would — but it means two different
        things depending on who set it, disambiguated once, at the top of
        the outer loop below, rather than separately in each branch:
        request_manual_wake() clears _paused_event before setting the
        event (a genuine "start a turn now"), while request_pause() sets
        _paused_event first (the event here only interrupts whatever's
        currently blocking so the loop can re-evaluate _paused_event
        immediately instead of whenever that blocking call happens to
        return on its own). So: _paused_event still set when the trigger
        is consumed means "just re-sync to the real paused state", not set
        means "actually start a turn". A single Event with two possible
        intents behind it, rather than a second one, keeps
        wake_word.listen_for_phrases's signature to one extra_stop_event
        instead of needing to interrupt on either of two.

        The full set of phrases checked in each pass — the stop word (if
        configured), the wake phrase(s), and the tray hide/show phrases — is
        resolved fresh from the profile on every pass through this loop via
        core/voice/special_phrases.py's REGISTRY (each iteration is one ~2s
        listening window, so this is a cheap sqlite read at that cadence,
        not a hot loop) rather than captured once when the thread started —
        it used to be fetched once in _run() before this method even existed
        as a loop, which meant setting a stop word for the first time via
        the personality settings panel (see modules/user_profile/handlers.py's
        profile_set) had no effect at all until the whole assistant was
        restarted: this method had already captured "no stop word" and never
        looked again.

        If a stop word is configured, it's listened for in the same pass as
        the wake word (see core/voice/wake_word.py's listen_for_phrases).
        Hearing it toggles self._paused_event and keeps looping internally
        instead of returning — pausing doesn't stop the thread, it just
        makes this method ignore the wake word until the same phrase is
        heard again.

        The tray hide/show phrases (modules/tray_hide) are folded into this
        exact same listen_for_phrases pass too, unconditionally (unlike the
        stop word, which only joins the pass once configured) —
        modules/tray_hide always has at least its default phrases, and
        hearing either one must work regardless of whether a stop word
        happens to be set. As a result this method no longer has a "fast
        path" that skips the STT-based listener for a plain single-phrase
        wake detector (see core/voice/wake_word.py's WakeWordDetector /
        get_wake_word_detector, e.g. the Porcupine backend): the arbitrary
        user-chosen tray phrases can only be recognized via STT, so the
        wake word rides along in the same pass rather than needing a second,
        independent listening stream on the same microphone. This is the
        single background audio stream both the wake-word and tray-hide
        detection share; hearing "hide" or "show" never returns from this
        method (the UI is not a voice command turn), it just requests the
        window visibility change and keeps listening."""
        while not self._stop_event.is_set():
            if self._manual_trigger_event.is_set():
                self._manual_trigger_event.clear()
                if not self._paused_event.is_set():
                    logger.info("Manual trigger received; starting a turn")
                    return True
                # else: this trigger was request_pause()'s own interrupt-
                # only use of the event (see its docstring) - fall through
                # to the paused branch below, which (re)broadcasts PAUSED
                # and genuinely starts listening for the resume phrase,
                # instead of a blocking call from before the pause was
                # requested just continuing to run as if nothing changed.

            if self._paused_event.is_set():
                # Re-asserted on every pass through this branch, not just
                # once when the pause was first requested (by the "pause"
                # branch below, a barge-in interruption, or
                # request_pause()) — a pause requested while a command turn
                # was still in flight (see request_pause's own docstring)
                # otherwise left /api/status showing whatever that turn's
                # own later state updates (processing/thinking/speaking/
                # idle) landed on once it finally finished, even though the
                # loop really had moved on to waiting here for the resume
                # phrase and wouldn't react to the wake word at all — a
                # real, observed live-testing bug, not hypothetical.
                state_manager.set_state(AssistantState.PAUSED, "Скажите стоп-слово ещё раз, чтобы продолжить")
                phrases = special_phrases.variants_for_context(self._settings, "paused")
                if "resume" not in phrases:
                    # Nothing to resume on; shouldn't normally happen since
                    # pausing requires a stop word, but don't get stuck here.
                    self._paused_event.clear()
                    continue
                heard = wake_word.listen_for_phrases(
                    self._settings,
                    phrases,
                    self._stop_event,
                    model_size=self._settings.whisper_model_size,
                    extra_stop_event=self._manual_trigger_event,
                )
                if heard == "resume":
                    self._paused_event.clear()
                    state_manager.set_state(AssistantState.IDLE)
                    logger.info("Stop word heard again; resuming")
                continue

            # Explicit "waiting for the activation phrase" state, distinct
            # from the LISTENING state _handle_command sets once "wake" is
            # actually heard below — see AssistantState.BACKGROUND_LISTENING
            # and CentralOrb.tsx, which renders the two noticeably
            # differently (quiet background pulse vs. active listening).
            state_manager.set_state(AssistantState.BACKGROUND_LISTENING, "Жду активационную фразу")

            # model_size=whisper_model_size (the bigger command tier, not
            # the fast wake-tier default): see wake_word.listen_for_phrases
            # for why an arbitrary user-chosen phrase (stop word, tray
            # hide/show, custom activation phrase) needs the more accurate
            # model to be recognized reliably. This does make wake-word
            # detection itself a bit slower than the fast single-word path
            # — but reliably honoring a pause/hide/show/wake request matters
            # more here than shaving time off wake latency.
            # "pause" comes out of REGISTRY ahead of "wake" on purpose: see
            # special_phrases.REGISTRY's own docstring — a stop word said
            # right after the wake/activation phrase in the same breath
            # ("привет стоп") must always win that race, never lose to
            # "wake" and get treated as ordinary command text that falls
            # through every local resolver straight into the AI-classification
            # fallback (see _classify_via_ai_bridge and its "Уточняю у ИИ"
            # state — that's what silently swallowing the stop word here used
            # to produce).
            phrases = special_phrases.variants_for_context(self._settings, "idle")
            heard = wake_word.listen_for_phrases(
                self._settings,
                phrases,
                self._stop_event,
                model_size=self._settings.whisper_model_size,
                extra_stop_event=self._manual_trigger_event,
            )
            if heard == "wake":
                return True
            if heard == "pause":
                self._paused_event.set()
                state_manager.set_state(AssistantState.PAUSED, "Скажите стоп-слово ещё раз, чтобы продолжить")
                logger.info("Stop word heard; pausing")
            elif heard == "tray_hide":
                self._speak_safely(tts, tray_hide_ack(self._ack_language()), self._ack_language())
                ui_control_service_layer.hide_window(state_manager)
                logger.info("Tray-hide phrase heard; hiding window")
            elif heard == "tray_show":
                self._speak_safely(tts, tray_show_ack(self._ack_language()), self._ack_language())
                ui_control_service_layer.show_window(state_manager)
                logger.info("Tray-show phrase heard; showing window")

        return False

    def _run(self) -> None:
        command_stt = SpeechToText(self._settings)
        tts = TextToSpeech(self._settings)

        self._run_onboarding_if_needed()

        while not self._stop_event.is_set():
            try:
                detected = self._wait_for_wake_or_pause(tts)
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

            # Fresh activation, fresh conversation - no memory of whatever
            # topic an earlier, already-ended session was about.
            self._last_exchange = None

            # Continuous conversation: one activation (spoken wake phrase
            # or the manual-trigger button) now covers a whole back-to-back
            # exchange, not just one command — after a command finishes
            # without being paused/interrupted, this goes straight into the
            # next _handle_command() instead of falling back to
            # _wait_for_wake_or_pause(), which would require the wake
            # phrase again. Found live: the assistant "ending the dialog"
            # after every single question, needing the wake phrase said
            # again for each follow-up, is exactly the behavior the user
            # reported and asked to have removed. Only a real pause (stop
            # word, mid-reply barge-in, or the "Завершить разговор" button
            # — both land here via self._paused_event) or a hard error ends
            # this inner loop; deliberately no silence/idle timeout of its
            # own, since the whole point is to keep listening until the
            # user explicitly stops it, exactly as asked. This makes
            # _maybe_continue_free_text's own narrower, shorter follow-up
            # window (free-text AI answers only) redundant in spirit but
            # not wrong to keep — it still gives a quick, low-latency
            # continuation for that one case before this broader,
            # unbounded wait would otherwise kick in.
            while not self._stop_event.is_set() and not self._paused_event.is_set():
                try:
                    interrupted = self._handle_command(command_stt, tts)
                except Exception:
                    # Retreat to requiring the wake phrase again rather than
                    # risking a tight retry loop with no blocking mic wait
                    # in between if _handle_command fails before it ever
                    # gets to one (e.g. SpeechToText/TextToSpeech
                    # construction itself broken) — same caution as the
                    # wake-word-detector except above, just scoped to not
                    # spinning *inside* an already-active conversation.
                    logger.exception("Voice command handling failed")
                    state_manager.set_state(AssistantState.IDLE)
                    break

                if interrupted:
                    # BargeInMonitor only ever sets this when it heard the
                    # user's own configured stop word mid-reply (see
                    # core/voice/barge_in.py) — the same phrase, the same
                    # meaning as everywhere else: a full pause, not "keep
                    # listening right away" (which this used to do at one
                    # point, skipping straight back into _handle_command
                    # unconditionally — a different, already-fixed bug from
                    # this same continuous-conversation behavior, which
                    # only ever re-enters _handle_command when NOT
                    # interrupted).
                    self._paused_event.set()
                    state_manager.set_state(AssistantState.PAUSED, "Скажите стоп-слово ещё раз, чтобы продолжить")
                    logger.info("Stop word heard while speaking; pausing")
                    break

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

        def on_progress(adapter_name: str) -> None:
            detail = _AI_ADAPTER_PROGRESS_DETAIL.get(adapter_name, "Уточняю у ИИ")
            state_manager.set_state(AssistantState.THINKING, detail)

        async def run() -> tuple[Command | None, str | None, bool | None]:
            speaker: _SentenceStreamSpeaker | None = None

            async def on_chunk(chunk: str) -> None:
                nonlocal speaker
                if speaker is None:
                    state_manager.set_state(AssistantState.SPEAKING)
                    speaker = _SentenceStreamSpeaker(tts, response_language, self._barge_in, self._stop_event)
                await speaker.feed(chunk)

            command, answer = await ai_router.resolve_free_text(
                text, commands, on_stream_chunk=on_chunk, on_progress=on_progress,
                context_hint=self._last_exchange,
            )
            if speaker is None or speaker.aborted:
                return command, answer, None
            return command, answer, await speaker.finish()

        try:
            # run_cancellable, not a bare asyncio.run(run()) — every other
            # AI-calling resolver in this file already goes through this so
            # a stop phrase said mid-call cancels it; this one used to be
            # the one exception, so saying the stop word while stuck on
            # "Уточняю у ИИ" (this state, set above) was silently unheard —
            # the barge-in monitor only started later, inside on_chunk,
            # once a streamed local-model answer actually began speaking.
            command, answer, streamed_interrupted = run_cancellable(run(), self._barge_in, response_language)
        except TurnCancelled:
            raise
        except Exception:
            logger.exception("AI intent classification failed")
            state_manager.set_state(AssistantState.SPEAKING)
            interrupted = self._speak_safely(tts, not_understood(response_language), response_language)
            return None, interrupted

        if command is not None:
            return command, False

        if answer is not None:
            # Recorded regardless of whether the answer ends up interrupted
            # below — the user's question and what was determined as its
            # answer are both valid context for a follow-up either way, the
            # interruption only affects whether it finished being *spoken*.
            self._last_exchange = f"Пользователь спросил: «{text}». Ассистент ответил: «{answer}»."
            record_assistant(answer, "voice")

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
        larger change than this first slice.

        The transcribed follow-up is checked against the stop word (see
        _pause_if_stop_word) before it's handed to the AI classifier —
        found missing via live testing: without it, saying the stop word
        right after an answer sent it into another AI round-trip as an
        ordinary follow-up question instead of pausing, which read as the
        stop word randomly "not working" rather than as a genuinely
        unhandled case one call site down from _handle_command's own
        backstop for the exact same thing."""
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
        if self._pause_if_stop_word(result.text, context="during a follow-up"):
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
            "recurrence": extracted.recurrence.value,
            "category": extracted.category,
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

        response = self._dispatch_ui_steps(steps, announcement, response_language)

        state_manager.set_state(AssistantState.SPEAKING)
        interrupted = self._speak_safely(tts, localize_response(response, response_language), response_language)
        return None, interrupted

    def _dispatch_ui_steps(
        self, steps: list[UIStep], announcement: str, response_language: str
    ) -> CommandResponse:
        """Shared tail of _resolve_ui_action and
        modules.os_agent's end-of-task apply step
        (_resolve_os_agent_task below): dispatches an already-resolved list
        of UIStep through the existing dangerous=True "ui_action" command
        and auto-confirms right after — the real gate for both callers is
        whatever happened before this is called (an uninterrupted spoken
        announcement for _resolve_ui_action, a real spoken yes for the
        os-agent's queued-actions confirmation), never a second prompt here."""
        params = {"steps": ui_service_layer.to_command_params(steps), "announcement": announcement}
        response = run_cancellable(
            self._dispatcher.dispatch("ui_action", params), self._barge_in, response_language
        )
        if response.status == CommandStatus.CONFIRMATION_REQUIRED and response.token:
            response = run_cancellable(
                self._dispatcher.confirm(response.token, True), self._barge_in, response_language
            )
        return response

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
        since there's nothing to *dispatch* — the whole game runs through
        modules.board_games.ui_session instead). Starts a new game and
        announces it; the actual turn-by-turn play happens through ordinary
        per-utterance commands afterward (see
        _resolve_active_board_game_utterance and _resolve_board_game_move
        below) — same shape as every other command in this file, not a
        captive loop, so the board updates after every half-move and a bare
        "пешка е4" works without needing to stay inside a special
        game-only listening state.

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
        session = board_games_ui_session.start(kind)
        state_manager.request_image(board_games_service_layer.render_svg(session))

        state_manager.set_state(AssistantState.SPEAKING)
        interrupted = self._speak_safely(tts, board_games_announce.game_started_text(kind), response_language)
        return None, interrupted

    def _resolve_active_board_game_utterance(self, text: str, response_language: str) -> Command | None:
        """Checked in _handle_command before interpret(), whenever
        modules.board_games.ui_session already has a game in progress — the
        same singleton the REST API (core/main.py's /api/boardgames/*) and
        BoardGamesPanel.tsx read from, so this is exactly the game the user
        is looking at, whether they started it by voice ("давай сыграем") or
        by clicking "Начать шахматы"/"Начать шашки". Lets a bare move
        ("пешка е3") apply directly, without first saying a trigger phrase —
        that gap (no intent pattern at all matched a bare move, and the old
        voice-only flow ran its own private GameSession the UI never saw)
        was the actual cause of "голосом не двигаются фигуры".

        Returns None (falls through to the normal interpret()/plugin/AI
        chain) when no game is active, or when resolve_player_move doesn't
        confidently match anything — deliberately not forcing a "не поняла
        ход" reply in that case, since an unrelated command said while a
        game happens to still be open ("открой браузер") must keep working
        normally, same trade-off already accepted for
        modules.ui_automation.grounding/modules.app_catalog.resolver."""
        session = board_games_ui_session.current()
        if session is None:
            return None
        if is_resign_command(text, response_language):
            return Command(name="board_game_resign", params={})
        matched = run_cancellable(
            board_games_service_layer.resolve_player_move(session, text), self._barge_in, response_language
        )
        if matched is None:
            return None
        return Command(name="board_game_apply_move", params={"notation": matched})

    def _resolve_board_game_move(self, command: Command, tts: TextToSpeech, response_language: str) -> bool:
        """Applies a move already resolved by
        _resolve_active_board_game_utterance, lets the engine reply, and
        pushes the updated board (state_manager.request_image) after each
        half-move — unlike the old captive loop this replaces, which only
        pushed the board once, after the whole game ended. Returns whether
        the spoken reply got barge-in-cut off."""
        session = board_games_ui_session.require_current()
        notation = command.params["notation"]

        board_games_service_layer.apply_player_move(session, notation)
        state_manager.request_image(board_games_service_layer.render_svg(session))
        if board_games_service_layer.is_over(session):
            return self._finish_board_game(tts, response_language)

        engine_move = board_games_service_layer.apply_engine_move(session)
        state_manager.request_image(board_games_service_layer.render_svg(session))

        speak_parts = [f"Вы сыграли {notation}.", board_games_announce.engine_move_text(engine_move.notation)]
        if board_games_service_layer.is_check(session):
            speak_parts.append(board_games_announce.check_text())
        state_manager.set_state(AssistantState.SPEAKING)
        interrupted = self._speak_safely(tts, " ".join(speak_parts), response_language)

        if board_games_service_layer.is_over(session):
            return self._finish_board_game(tts, response_language) or interrupted
        return interrupted

    def _finish_board_game(self, tts: TextToSpeech, response_language: str, resigned: bool = False) -> bool:
        """Ends whatever game is current in ui_session (releasing the chess
        engine subprocess, if any) and speaks the result + mistake summary —
        called both when a move ends the game naturally and when the player
        resigns. No-ops (returns False) if there's no active game, which
        can't normally happen given both call sites check first, but keeps
        this safe to call defensively."""
        summary = board_games_ui_session.finish()
        if summary is None:
            return False
        state_manager.request_image(summary.board_svg)
        lines = [board_games_announce.game_stopped_text()] if resigned else []
        lines.append(board_games_announce.result_text(summary.result_string))
        lines.append(board_games_announce.summary_intro_text(len(summary.mistakes)))
        lines.extend(board_games_announce.mistake_text(m) for m in summary.mistakes)
        state_manager.set_state(AssistantState.SPEAKING)
        return self._speak_safely(tts, " ".join(lines), response_language)

    def _resolve_active_os_agent_utterance(self, text: str, response_language: str) -> Command | None:
        """Checked in _handle_command right alongside
        _resolve_active_board_game_utterance, before interpret() — while
        modules.os_agent.session is active (agent mode on, waiting for a
        task), every utterance is claimed here instead of going through
        normal command interpretation: either a stop phrase (is_stop_command/
        STOP_PHRASES — a fixed word list, deliberately not the user's own
        configured stop word from core/voice/special_phrases.py; exiting
        agent mode doesn't need a separate exit-phrase set) or free-text task
        description. Returns None only when the mode isn't active at all, so
        an unrelated utterance keeps working normally when it happens to
        arrive while the mode is off."""
        if not os_agent_session.is_active():
            return None
        if is_stop_command(text, response_language):
            return Command(name="stop_os_agent", params={})
        return Command(name="os_agent_run_task", params={"raw_text": text})

    def _resolve_active_fitness_context_utterance(self, text: str, response_language: str) -> Command | None:
        """Checked in _handle_command right alongside
        _resolve_active_board_game_utterance/_resolve_active_os_agent_utterance,
        before interpret() — but unlike those two, this ALWAYS claims the
        utterance once modules.fitness_tracker.context_state.is_active(),
        never returning None: the task spec explicitly wants an utterance
        that doesn't match any fitness intent category to be treated as a
        question for fitness_chat.py, not silently handed back to the
        normal interpret()/AI-classifier pipeline (see
        modules.fitness_tracker.intent_parser.parse's own docstring).
        Mirrors os_agent's split between a text-only early resolver and a
        separate TTS-capable resolve method: the actual parse/exit/apply
        decision happens in _resolve_fitness_utterance below, which has
        tts/command_stt access for a clarifying follow-up question — this
        method only tags the utterance and hands the raw text along, the
        same way os_agent_run_task's params carry raw_text rather than
        anything already parsed. Returns None only when the context isn't
        active at all, so interpret() gets a chance to recognize the
        activation phrase itself (core/voice/intent.py's
        _FITNESS_START_PHRASES)."""
        if not fitness_context_state.is_active():
            return None
        return Command(name="fitness_utterance", params={"text": text})

    def _resolve_fitness_activate(self, tts: TextToSpeech, response_language: str) -> bool:
        fitness_context_state.activate()
        fitness_chat.reset_api_key_hint()
        state_manager.set_state(AssistantState.SPEAKING)
        return self._speak_safely(tts, fitness_announce.context_activated_text(response_language), response_language)

    def _resolve_fitness_clarify(
        self, parsed: ParsedIntent, tts: TextToSpeech, command_stt: SpeechToText, response_language: str
    ) -> tuple[ParsedIntent, bool]:
        """One follow-up voice round for a ParsedIntent missing a required
        field (e.g. "замерь бицепс" with no number) — same "speak a
        question, listen once, use the answer" shape as
        _resolve_board_game's which-game prompt. Returns the original
        `parsed` unchanged (still incomplete) if the question itself gets
        barge-in-cut off, so the caller's own missing_fields check decides
        what to do next rather than this method guessing."""
        question = fitness_voice_commands.clarify_question_text(parsed, response_language)
        state_manager.set_state(AssistantState.SPEAKING)
        if self._speak_safely(tts, question, response_language):
            return parsed, True

        state_manager.set_state(AssistantState.LISTENING, "Жду ответа")
        answer_audio = audio_io.record_until_silence(self._settings, self._stop_event)
        answer_text = command_stt.transcribe(answer_audio).text
        return fitness_voice_commands.merge_followup(parsed, answer_text), False

    def _resolve_fitness_chat_question(self, text: str, tts: TextToSpeech, response_language: str) -> bool:
        state_manager.set_state(AssistantState.PROCESSING)
        try:
            reply = run_cancellable(
                fitness_chat.answer_question(text, response_language), self._barge_in, response_language
            )
        except TurnCancelled:
            raise
        except fitness_chat.FitnessChatError:
            state_manager.set_state(AssistantState.SPEAKING)
            return self._speak_safely(tts, not_understood(response_language), response_language)
        state_manager.set_state(AssistantState.SPEAKING)
        return self._speak_safely(tts, reply, response_language)

    def _resolve_fitness_utterance(
        self, command: Command, tts: TextToSpeech, command_stt: SpeechToText, response_language: str
    ) -> bool:
        """The actual fitness-context decision, made here (rather than in
        _resolve_active_fitness_context_utterance above) because it needs
        tts/command_stt for both the clarifying follow-up round and for
        speaking whatever the outcome is — same split rationale as
        os_agent_run_task/_resolve_os_agent_task."""
        text = command.params.get("text", "")

        if is_fitness_exit_command(text, response_language):
            fitness_context_state.deactivate()
            state_manager.set_state(AssistantState.SPEAKING)
            return self._speak_safely(
                tts, fitness_announce.context_deactivated_text(response_language), response_language
            )

        fitness_context_state.touch()
        parsed = fitness_intent_parser.parse(text)

        if parsed.category is None:
            return self._resolve_fitness_chat_question(text, tts, response_language)

        if parsed.missing_fields:
            parsed, interrupted = self._resolve_fitness_clarify(parsed, tts, command_stt, response_language)
            if interrupted:
                return True
            if parsed.missing_fields:
                state_manager.set_state(AssistantState.SPEAKING)
                return self._speak_safely(tts, not_understood(response_language), response_language)

        state_manager.set_state(AssistantState.PROCESSING)
        try:
            reply = run_cancellable(
                fitness_voice_commands.apply_intent(parsed, response_language), self._barge_in, response_language
            )
        except TurnCancelled:
            raise
        except Exception:
            logger.exception("Applying a fitness intent failed")
            state_manager.set_state(AssistantState.SPEAKING)
            return self._speak_safely(tts, not_understood(response_language), response_language)

        state_manager.set_state(AssistantState.SPEAKING)
        return self._speak_safely(tts, reply, response_language)

    def _resolve_os_agent_start(self, tts: TextToSpeech, response_language: str) -> bool:
        """Called for a "start_os_agent" command (see
        core/voice/intent.py's _OS_AGENT_START_PHRASES). Hard-refuses before
        the mode even turns on if neither a Gemini nor a Claude key is
        configured (modules.os_agent.planner.has_configured_key) — per the
        agreed plan, no browser-automation fallback for this feature, so
        there's nothing to fall back to. Returns whether the spoken reply
        got barge-in-cut off."""
        state_manager.set_state(AssistantState.SPEAKING)
        if not os_agent_planner.has_configured_key():
            return self._speak_safely(
                tts, os_agent_announce.no_key_refusal_text(response_language), response_language
            )
        os_agent_session.start()
        return self._speak_safely(tts, os_agent_announce.mode_started_text(response_language), response_language)

    def _resolve_os_agent_task(
        self, command: Command, tts: TextToSpeech, command_stt: SpeechToText, response_language: str
    ) -> bool:
        """Runs the whole autonomous loop for one task
        (modules.os_agent.runner.run_task) inside this single voice turn,
        then — if it produced anything queued — speaks the numbered plan and
        blocks for one real spoken yes/no (same shape as
        _confirm_custom_command, not the generic dangerous-token
        auto-confirm flow — the spoken answer here IS the real gate). Always
        turns agent mode back off before returning (one task per activation,
        see modules/os_agent/session.py's docstring), and returns whether
        the last thing spoken got barge-in-cut off."""
        raw_text = command.params.get("raw_text", "").strip()
        try:
            session = run_cancellable(os_agent_runner.run_task(raw_text), self._barge_in, response_language)
        except TurnCancelled:
            os_agent_session.finish()
            raise
        except Exception:
            logger.exception("os_agent task run failed")
            os_agent_session.finish()
            state_manager.set_state(AssistantState.SPEAKING)
            return self._speak_safely(tts, not_understood(response_language), response_language)

        if not session.pending:
            if session.outcome == "done":
                text = session.summary or "Готово."
            elif session.outcome == "throttled":
                text = os_agent_announce.throttled_text(response_language)
            else:
                text = os_agent_announce.stuck_text(session.summary or "", response_language)
            state_manager.set_state(AssistantState.SPEAKING)
            interrupted = self._speak_safely(tts, text, response_language)
            os_agent_session.finish()
            return interrupted

        announcement = os_agent_announce.queue_summary(
            session.pending, response_language, step_limit_reached=session.outcome == "limit"
        )
        question = f"{announcement} {os_agent_announce.confirm_question_text(response_language)}"
        state_manager.set_state(AssistantState.SPEAKING)
        if self._speak_safely(tts, question, response_language):
            os_agent_session.finish()
            return True

        state_manager.set_state(AssistantState.LISTENING, "Жду подтверждения")
        confirm_audio = audio_io.record_until_silence(self._settings, self._stop_event)
        confirm_result = command_stt.transcribe(confirm_audio)
        approved = is_affirmative(confirm_result.text, response_language)

        if approved:
            response = self._dispatch_ui_steps(session.pending, announcement, response_language)
            state_manager.set_state(AssistantState.SPEAKING)
            interrupted = self._speak_safely(
                tts, localize_response(response, response_language), response_language
            )
        else:
            state_manager.set_state(AssistantState.SPEAKING)
            interrupted = self._speak_safely(
                tts, os_agent_announce.cancelled_text(response_language), response_language
            )

        if not interrupted:
            interrupted = self._offer_os_agent_explanation(session, tts, command_stt, response_language)

        os_agent_session.finish()
        return interrupted

    def _offer_os_agent_explanation(
        self, session: AgentSession, tts: TextToSpeech, command_stt: SpeechToText, response_language: str
    ) -> bool:
        """One optional voice round after an os-agent task with a non-empty
        queue (applied or cancelled either way) — "want me to explain why?"
        — per the agreed plan's "опциональный вопрос-ответ" journal feature.
        Deliberately a single fixed offer+answer, not open-ended follow-up
        Q&A, to keep this v1 slice bounded."""
        state_manager.set_state(AssistantState.SPEAKING)
        if self._speak_safely(tts, os_agent_announce.explain_offer_text(response_language), response_language):
            return True

        state_manager.set_state(AssistantState.LISTENING, "Жду ответа")
        answer_audio = audio_io.record_until_silence(self._settings, self._stop_event)
        answer_result = command_stt.transcribe(answer_audio)
        if not is_affirmative(answer_result.text, response_language):
            return False

        explanation = run_cancellable(os_agent_planner.explain(session), self._barge_in, response_language)
        state_manager.set_state(AssistantState.SPEAKING)
        text = explanation or "Не получилось сформулировать объяснение."
        return self._speak_safely(tts, text, response_language)

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

    def _resolve_edit_pending_message(
        self, command: Command, command_stt: SpeechToText, tts: TextToSpeech, response_language: str
    ) -> tuple[Command | None, bool]:
        """Called for an "edit_pending_message" command before it's
        dispatched (see core/voice/intent.py's _TEXT_EDIT_MESSAGE_PATTERNS).
        Finds the target message the same way
        _resolve_messaging_reply/_resolve_messaging_snooze do, then always
        asks "какую инструкцию дать?" — unlike _resolve_messaging_snooze's
        local duration parser, there's no rule-based way to guess an
        arbitrary edit instruction from the raw captured text, so this
        never tries to skip the question. The actual edit happens in
        modules.text_editing's dispatcher handler once this hands back an
        enriched Command — this method only resolves *which* message and
        *what* to do with it, same division of labor as
        _resolve_messaging_snooze."""
        raw_target = command.params.get("raw_target", "")
        target, interrupted = self._resolve_pending_message_target(
            raw_target, tts, command_stt, response_language
        )
        if target is None:
            return None, interrupted

        state_manager.set_state(AssistantState.SPEAKING)
        if self._speak_safely(tts, "Какую инструкцию дать?", response_language):
            return None, True

        state_manager.set_state(AssistantState.LISTENING, "Слушаю инструкцию")
        instruction_audio = audio_io.record_until_silence(self._settings, self._stop_event)
        instruction = command_stt.transcribe(instruction_audio).text.strip()
        if not instruction:
            state_manager.set_state(AssistantState.SPEAKING)
            interrupted = self._speak_safely(tts, not_understood(response_language), response_language)
            return None, interrupted

        return Command(name=command.name, params={"message_id": target.id, "instruction": instruction}), False

    def _resolve_analyze_active_editor(
        self, command: Command, command_stt: SpeechToText, tts: TextToSpeech, response_language: str
    ) -> tuple[Command | None, bool]:
        """Called for an "analyze_active_editor" command before it's
        dispatched (see core/voice/intent.py's _CODE_ANALYSIS_PATTERNS).
        Always asks "что именно сделать с кодом?" — same reasoning as
        _resolve_edit_pending_message: there's no rule-based way to guess an
        arbitrary analysis instruction from a bare "проанализируй код"."""
        state_manager.set_state(AssistantState.SPEAKING)
        if self._speak_safely(tts, "Что именно сделать с кодом?", response_language):
            return None, True

        state_manager.set_state(AssistantState.LISTENING, "Слушаю задачу")
        instruction_audio = audio_io.record_until_silence(self._settings, self._stop_event)
        instruction = command_stt.transcribe(instruction_audio).text.strip()
        if not instruction:
            state_manager.set_state(AssistantState.SPEAKING)
            interrupted = self._speak_safely(tts, not_understood(response_language), response_language)
            return None, interrupted

        return Command(name=command.name, params={"instruction": instruction}), False

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

    def _confirm_custom_command(
        self, trigger_phrase: str, command_stt: SpeechToText, tts: TextToSpeech, response_language: str
    ) -> tuple[bool, bool]:
        """One-shot spoken yes/no for a matched custom command
        (modules/custom_commands), asked only when
        CUSTOM_COMMANDS_REQUIRE_CONFIRMATION_KEY is enabled and only for
        launch_app/text_instruction (see that profile-fact's own comment
        for why those two specifically). Same shape as
        _resolve_open_app_target's "did you mean X?".

        This checks the setting itself fresh on every call rather than
        relying on CommandDispatcher's dangerous=True/token mechanism
        (which modules/custom_commands/dispatcher.py deliberately does NOT
        use for this) — see that module's register_one for why: the
        setting can be toggled without touching any individual custom
        command, so a cached dangerous flag would go stale until the next
        unrelated CRUD action re-registered it.

        Returns (approved, interrupted) — interrupted True only if the
        question itself got barge-in-cut off mid-sentence."""
        state_manager.set_state(AssistantState.SPEAKING)
        question = f"Выполнить «{trigger_phrase}»?"
        if self._speak_safely(tts, question, response_language):
            return False, True

        state_manager.set_state(AssistantState.LISTENING, "Жду подтверждения")
        confirm_audio = audio_io.record_until_silence(self._settings, self._stop_event)
        confirm_result = command_stt.transcribe(confirm_audio)
        return is_affirmative(confirm_result.text, response_language), False

    def _pause_if_stop_word(self, text: str, *, context: str) -> bool:
        """Checks `text` — something already transcribed outside
        _wait_for_wake_or_pause's own listen_for_phrases pass, which
        already listens for the stop word as one of its phrases — against
        the configured stop word (with a Latin-transliterated variant,
        since a short single-word STT transcription routinely misfires the
        alphabet; see with_transliterated_variant). On a match, pauses
        immediately (sets _paused_event/PAUSED state, same as every other
        pause path in this file) and returns True so the caller drops
        `text` instead of treating it as a real command or free-text
        question. `context` only flavors the log line (e.g. "as the
        command itself", "during a follow-up") to tell call sites apart.

        Found live: _maybe_continue_free_text's follow-up window used to
        have no stop-word check at all, so saying the stop word there sent
        it straight into another AI round-trip (candidate_chain/ai_router)
        as if it were a genuine follow-up question, instead of pausing —
        which read as the stop word "not working"/hanging rather than as
        the real bug, a missing check one call site down from the one that
        already had it (_handle_command's own backstop below)."""
        stop_word = profile_service_layer.get_fact(ProfileUnitOfWork(), STOP_WORD_KEY)
        if not stop_word or not fuzzy_matches_any(text, with_transliterated_variant(stop_word)):
            return False
        self._paused_event.set()
        state_manager.set_state(AssistantState.PAUSED, "Скажите стоп-слово ещё раз, чтобы продолжить")
        logger.info("Stop word heard %s; pausing", context)
        return True

    def _handle_command(self, command_stt: SpeechToText, tts: TextToSpeech) -> bool:
        """Returns True if the user barge-in-interrupted the spoken reply
        (or the recording of their own command, or the "thinking" in
        between — see _record_command_audio/run_cancellable) with the stop
        word — see VoiceAssistantLoop._run, which then pauses (same as
        _wait_for_wake_or_pause's own "pause" branch) instead of listening
        for a new command right away."""
        state_manager.set_state(AssistantState.LISTENING, "Слушаю команду")
        audio, interrupted = self._record_command_audio()
        if interrupted:
            return True
        if audio.size == 0:
            state_manager.set_state(AssistantState.IDLE)
            return False

        state_manager.set_state(AssistantState.PROCESSING, "Распознаю")
        result = command_stt.transcribe(audio)
        logger.info(
            "STT transcribed: %r (detected_language=%s, probability=%.2f)",
            result.text, result.detected_language, result.language_probability,
        )

        # Backstop for _record_command_audio's own live BargeInMonitor
        # (context="recording") above — that one covers the ordinary case
        # (stop word heard mid-utterance cuts the recording short right
        # away), but two things can still slip past it: the second mic
        # stream failing to open at all on this audio backend (silent
        # best-effort degradation — see BargeInMonitor.run), or the stop
        # word being said so close to the very end of the utterance that
        # VAD silence-detection already ended the recording before the
        # live monitor's own ~1.2s window got a chance to transcribe it.
        # Either way, this text-level check on what actually got
        # transcribed still catches it before interpret()/custom_commands/
        # board-game ever sees it — mirrors the same pause behavior
        # _wait_for_wake_or_pause uses for "heard == pause": set
        # _paused_event and go straight to PAUSED, no command processing
        # at all for this turn.
        if self._pause_if_stop_word(result.text, context="as the command itself"):
            return False

        record_user(result.text, "voice")

        decision = resolve_language(result.detected_language, result.language_probability, self._settings)
        # decision.resolved drives interpretation of the user's own words (interpret,
        # is_affirmative); response_language drives what the assistant speaks back and
        # may differ from it when response_language_override is configured.
        response_language = resolve_response_language(decision.resolved, self._settings)

        self._learn_facts(result.text, decision.resolved)

        # A time marker anywhere in the utterance ("... через 10 минут",
        # "... в 18 часов") schedules whatever is left for later instead of
        # running it now — checked before the multi-command split so a
        # single delayed command with an "и" in its object still schedules
        # as one. See modules/delayed_execution.
        delay = delayed_command_parser.extract_delay(result.text, decision.resolved)
        if delay is not None:
            interrupted = self._schedule_delayed_command(
                delay, result.text, command_stt, tts, decision, response_language
            )
            state_manager.set_state(AssistantState.IDLE)
            return interrupted

        # A chained utterance ("выключи звук и сверни окно") runs as a
        # sequence of independent commands, each through the full resolve/
        # dispatch path below — but only when the whole thing isn't itself a
        # single custom trigger phrase or one rule-based command that merely
        # contains "и"/"потом"/a comma. See modules/multi_command_parser.
        parts = multi_command_parser.split_commands(result.text, decision.resolved)
        if (
            len(parts) > 1
            and custom_commands.match(result.text) is None
            and interpret(result.text, decision.resolved) is None
        ):
            interrupted = False
            for part in parts:
                interrupted = self._resolve_and_run_one(
                    part, command_stt, tts, decision, response_language, part_of_multi=True
                )
                if interrupted:
                    break
            state_manager.set_state(AssistantState.IDLE)
            return interrupted
        return self._resolve_and_run_one(result.text, command_stt, tts, decision, response_language)

    def _schedule_delayed_command(
        self,
        delay: delayed_command_parser.DelaySpec,
        original_text: str,
        command_stt: SpeechToText,
        tts: TextToSpeech,
        decision: LanguageDecision,
        response_language: str,
    ) -> bool:
        """Resolves the non-time part of the utterance to a command and
        stores it to run at delay.run_at instead of now. A dangerous command
        is confirmed out loud right here (there is nobody to ask when the
        timer elapses — it then fires via dispatch_preconfirmed). Returns
        True on a stop-word barge-in, same as _resolve_and_run_one."""
        command = delayed_resolver.resolve_command(delay.remainder, decision.resolved)
        if command is None:
            state_manager.set_state(AssistantState.SPEAKING)
            return self._speak_safely(
                tts, f"Не понял, что именно отложить: «{delay.remainder}».", response_language
            )

        pre_confirmed = False
        if self._dispatcher.is_dangerous(command.name):
            state_manager.set_state(AssistantState.SPEAKING)
            if self._speak_safely(
                tts,
                f"Отложить «{delay.remainder}» на {delay.spoken_delay}? Это действие требует подтверждения.",
                response_language,
            ):
                return True
            state_manager.set_state(AssistantState.LISTENING, "Жду подтверждения")
            confirm_audio = audio_io.record_until_silence(self._settings, self._stop_event)
            confirm_result = command_stt.transcribe(confirm_audio)
            if not is_affirmative(confirm_result.text, decision.resolved):
                state_manager.set_state(AssistantState.SPEAKING)
                return self._speak_safely(tts, "Хорошо, не откладываю.", response_language)
            pre_confirmed = True

        delayed_service_layer.schedule(
            DelayedExecutionUnitOfWork(), command, delay.run_at, original_text, pre_confirmed
        )
        state_manager.set_state(AssistantState.SPEAKING)
        return self._speak_safely(
            tts, f"Хорошо, «{delay.remainder}» — через {delay.spoken_delay}.", response_language
        )

    def _resolve_and_run_one(
        self,
        raw_text: str,
        command_stt: SpeechToText,
        tts: TextToSpeech,
        decision: LanguageDecision,
        response_language: str,
        *,
        part_of_multi: bool = False,
    ) -> bool:
        """Resolves one command's text — the whole utterance, or a single
        segment of a chained "X и Y" utterance (see multi_command_parser) —
        through the custom-command / interpret() / plugin / local-classifier /
        AI chain, then dispatches it. Returns True when a stop-word barge-in
        interrupted this segment (its spoken reply, the recording of a
        follow-up, or the dispatch itself), which the caller treats exactly
        as _handle_command's own return does."""
        # Custom commands (modules/custom_commands) are checked before even
        # the rule-based interpret() — a user-authored trigger phrase is
        # meant to be an unconditional personal shortcut, so it must win
        # over generic built-in interpretation too, not just over the AI
        # fallback. This does mean a carelessly chosen trigger phrase could
        # shadow a built-in command; that's the same accepted trade-off
        # modules/plugin_agent's trigger phrases already carry today, not a
        # new risk category.
        text_to_interpret = raw_text
        custom_match = custom_commands.match(raw_text)
        if custom_match is not None:
            # launch_app runs an arbitrary stored executable path and
            # text_instruction can trigger anything the AI/command pipeline
            # is capable of — both optionally gated behind one spoken
            # yes/no first. open_link/play_audio/open_media just open
            # something, same risk tier as the existing open_app command,
            # so they're never gated here. Off by default — see
            # modules/user_profile/domain.py's
            # CUSTOM_COMMANDS_REQUIRE_CONFIRMATION_KEY.
            needs_confirmation = (
                custom_match.action_type in (ActionType.LAUNCH_APP, ActionType.TEXT_INSTRUCTION)
                and custom_commands.requires_confirmation()
            )
            if needs_confirmation:
                approved, interrupted = self._confirm_custom_command(
                    custom_match.trigger_phrase, command_stt, tts, response_language
                )
                if interrupted:
                    state_manager.set_state(AssistantState.IDLE)
                    return True
                if not approved:
                    state_manager.set_state(AssistantState.SPEAKING)
                    self._speak_safely(tts, "Хорошо, не выполняю.", response_language)
                    state_manager.set_state(AssistantState.IDLE)
                    return False

            if custom_match.action_type is ActionType.TEXT_INSTRUCTION:
                # A TEXT_INSTRUCTION custom command is a personal shortcut
                # for a longer spoken request — e.g. a trigger phrase
                # "напиши маме" standing in for "напиши в телеграм маме что
                # я задержусь". Substitute the stored instruction in place
                # of what was actually said and let it flow through the
                # normal chain below exactly once — custom_match is cleared
                # so it isn't re-checked against custom commands again,
                # guarding against an instruction that itself happens to
                # match another trigger phrase turning into an alias loop.
                text_to_interpret = custom_match.action_payload.get("instruction", "")
                custom_match = None

        if custom_match is not None:
            command: Command | None = Command(
                name=custom_commands.dispatcher_command_name(custom_match.id), params={}
            )
        else:
            # Checked before interpret() itself: a bare move ("пешка е3")
            # against a game already in progress must win over every other
            # interpretation, the same priority custom commands get above —
            # see _resolve_active_board_game_utterance's own docstring.
            command = self._resolve_active_board_game_utterance(text_to_interpret, response_language)
            if command is None:
                command = self._resolve_active_os_agent_utterance(text_to_interpret, response_language)
            if command is None:
                command = self._resolve_active_fitness_context_utterance(text_to_interpret, response_language)
            if command is None:
                command = interpret(text_to_interpret, decision.resolved)
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
                command = match_plugin_command(text_to_interpret)
            if command is None:
                # Fast, fully local system-command filter (volume, windows,
                # filesystem, language, battery, updates) — tried before ever
                # spending time/quota on an external AI provider. See
                # modules/hardware_adaptive/command_classifier.py's module
                # docstring for why this sits here, between plugin matching and
                # the AI classifier.
                command = command_classifier.match_system_command(text_to_interpret)
            if command is None:
                # Own try/except here rather than relying on the big
                # try/except TurnCancelled below (starting at the
                # command.name dispatch): that one only wraps resolving a
                # command's *parameters* and dispatch()/confirm() itself —
                # this call happens earlier, while `command` is still being
                # determined at all, so it isn't covered by it. Mirrors that
                # same block's own TurnCancelled handling exactly (stop
                # silently, listen again immediately, no error logged).
                try:
                    command, interrupted = self._classify_via_ai_bridge(
                        text_to_interpret, command_stt, tts, response_language
                    )
                except TurnCancelled:
                    state_manager.set_state(AssistantState.IDLE)
                    return True
                if command is None:
                    # As one segment of a chained utterance, a silent bail
                    # would leave the user unsure which part failed — name it,
                    # the way the stateless endpoint's combined reply does
                    # (see web_pipeline._resolve_and_dispatch_multi). Standalone,
                    # _classify_via_ai_bridge has already said its piece.
                    if part_of_multi and not interrupted:
                        state_manager.set_state(AssistantState.SPEAKING)
                        interrupted = self._speak_safely(
                            tts, f"Часть «{raw_text}» не понял.", response_language
                        )
                    state_manager.set_state(AssistantState.IDLE)
                    return interrupted

        # `command` is now a real command about to be resolved/dispatched —
        # as opposed to a plain conversational answer, which
        # _classify_via_ai_bridge already speaks and returns from above
        # without ever reaching here. This is the single choke point every
        # command type passes through (system command, custom command,
        # plugin match, Figma/Blender command, ...), so it's also the right
        # place for the Jarvis-style "Да, сэр"/"Да, мэм" acknowledgement —
        # see modules/user_profile/domain.py's CONFIRMATION_PHRASE_ENABLED_KEY
        # — and for recording this turn as the session's _last_exchange
        # (see its own docstring in __init__) regardless of which tier
        # resolved it (rule-based interpret(), a custom/plugin trigger, the
        # local embedding classifier, or the AI classifier) — a later
        # elliptical follow-up needs this recorded no matter how *this*
        # turn itself got resolved.
        self._last_exchange = (
            f"Пользователь сказал: «{text_to_interpret}». Ассистент выполнил команду "
            f"{command.name} с параметрами {command.params}."
        )

        if confirmation_phrase.is_enabled():
            state_manager.set_state(AssistantState.SPEAKING)
            if self._speak_safely(tts, confirmation_phrase.get_confirmation_phrase(), response_language):
                state_manager.set_state(AssistantState.IDLE)
                return True

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
            elif command.name == "start_os_agent":
                interrupted = self._resolve_os_agent_start(tts, response_language)
                state_manager.set_state(AssistantState.IDLE)
                return interrupted
            elif command.name == "stop_os_agent":
                os_agent_session.finish()
                state_manager.set_state(AssistantState.SPEAKING)
                interrupted = self._speak_safely(
                    tts, os_agent_announce.mode_stopped_text(response_language), response_language
                )
                state_manager.set_state(AssistantState.IDLE)
                return interrupted
            elif command.name == "os_agent_run_task":
                interrupted = self._resolve_os_agent_task(command, tts, command_stt, response_language)
                state_manager.set_state(AssistantState.IDLE)
                return interrupted
            elif command.name == "fitness_activate_context":
                interrupted = self._resolve_fitness_activate(tts, response_language)
                state_manager.set_state(AssistantState.IDLE)
                return interrupted
            elif command.name == "fitness_utterance":
                interrupted = self._resolve_fitness_utterance(command, tts, command_stt, response_language)
                state_manager.set_state(AssistantState.IDLE)
                return interrupted
            elif command.name == "board_game_apply_move":
                interrupted = self._resolve_board_game_move(command, tts, response_language)
                state_manager.set_state(AssistantState.IDLE)
                return interrupted
            elif command.name == "board_game_resign":
                interrupted = self._finish_board_game(tts, response_language, resigned=True)
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
            elif command.name == "edit_pending_message":
                command, interrupted = self._resolve_edit_pending_message(
                    command, command_stt, tts, response_language
                )
                if command is None:
                    state_manager.set_state(AssistantState.IDLE)
                    return interrupted
            elif command.name == "analyze_active_editor":
                command, interrupted = self._resolve_analyze_active_editor(
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
                # yes/no answer (BargeInMonitor only recognizes the stop word,
                # never "да"). Bailing used to silently abandon the token and
                # let the next loop iteration treat whatever the user said
                # next as a brand new top-level command instead of the
                # answer to this question - the exact
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
