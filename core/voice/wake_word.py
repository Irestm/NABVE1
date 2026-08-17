from __future__ import annotations

import threading
from abc import ABC, abstractmethod

import numpy as np

from core.voice.audio_io import RollingAudioBuffer, require_sounddevice
from core.voice.config import VoiceSettings
from core.voice.phrase_matching import fuzzy_matches_any
from core.voice.stt import SpeechToText

# Natural variations of the default Russian wake phrase, so "Привет!" said
# plainly, "Привет, Джарвис" and "Эй, Джарвис" all activate the assistant
# without the user needing to know one exact configured string. See
# resolve_wake_phrases, the only place this is read.
DEFAULT_WAKE_PHRASES: tuple[str, ...] = ("привет", "привет джарвис", "эй джарвис", "привет набве")


def resolve_wake_phrases(settings: VoiceSettings, custom_phrase: str | None) -> tuple[str, ...]:
    """The full set of phrases that should activate the assistant:
    DEFAULT_WAKE_PHRASES, settings.wake_word (kept for backwards
    compatibility with anyone already relying on the older single-word
    ASSISTANT_WAKE_WORD env var), and the user's own custom phrase from the
    "Активационная фраза" settings field if they've set one — same
    default-plus-custom shape as modules/tray_hide/detector.py's
    hide_phrases/show_phrases. Added to the defaults, not replacing them, so
    setting a custom phrase never silently disables "привет"/"эй джарвис"
    for a user who forgets they set one. Deduplicated
    (case/whitespace-insensitively) since settings.wake_word's default,
    "ассистент", or a custom phrase may coincide with a default entry."""
    seen: set[str] = set()
    phrases: list[str] = []
    for phrase in (*DEFAULT_WAKE_PHRASES, settings.wake_word, custom_phrase or ""):
        normalized = phrase.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        phrases.append(phrase.strip())
    return tuple(phrases)


class WakeWordDetector(ABC):
    @abstractmethod
    def listen(self, stop_event: threading.Event) -> bool:
        raise NotImplementedError


def _listen_for_any(
    stt: SpeechToText,
    settings: VoiceSettings,
    phrases: dict[str, str | tuple[str, ...]],
    stop_event: threading.Event,
) -> str | None:
    """Polls the mic in settings.wake_word_check_interval_seconds-spaced
    2s windows, transcribing each and fuzzy-matching against every phrase in
    `phrases` (name -> phrase text, or name -> a tuple of interchangeable
    phrase variants — e.g. modules/tray_hide's default/custom hide-phrase
    list, all of which should count as the same "name" matching), until one
    matches or `stop_event` is set. Returns the matching name, or None if
    `stop_event` fired first. Shared by KeywordWakeWordDetector.listen and
    listen_for_phrases so checking multiple phrases (e.g. the wake word and
    a configured stop word) costs one STT pass per window instead of one per
    phrase.

    Transcription is pinned to settings.fallback_language rather than left
    on Whisper's own per-window autodetect: a short 2s window containing
    just one or two words (exactly what a wake word or a one-word stop
    word usually is) gives Whisper's language-ID pass very little to go on,
    and it routinely guessed wrong — a stop word saved as "нос" came back
    transcribed as "¡Nos!"/"NOS" (detected as Spanish/English) often enough
    that fuzzy_contains_phrase, which has no notion of cross-alphabet
    equivalence, could never match it against the stored Cyrillic phrase.
    The same short utterance surrounded by a couple of extra words
    transcribed correctly (more audio for language-ID to work with), which
    is exactly the "sometimes it hears it, mostly it doesn't" symptom this
    fixes. This assistant is single-user and single-language by design (see
    VoiceSettings.fallback_language) so pinning here, rather than trying to
    plumb a live language preference into a background thread, is correct
    for every deployment of it, not just a workaround."""
    buffer = RollingAudioBuffer(settings, window_seconds=2.0)
    buffer.start()
    try:
        while not stop_event.is_set():
            window = buffer.read_window(timeout=settings.wake_word_check_interval_seconds)
            if window.size == 0:
                continue
            result = stt.transcribe(window, settings.fallback_language)
            for name, phrase in phrases.items():
                variants = (phrase,) if isinstance(phrase, str) else phrase
                if fuzzy_matches_any(result.text, variants):
                    return name
        return None
    finally:
        buffer.stop()


class KeywordWakeWordDetector(WakeWordDetector):
    def __init__(self, settings: VoiceSettings) -> None:
        self._settings = settings
        self._stt = SpeechToText(settings, model_size=settings.whisper_wake_model_size)

    def listen(self, stop_event: threading.Event) -> bool:
        return _listen_for_any(self._stt, self._settings, {"wake": self._settings.wake_word}, stop_event) == "wake"


class PorcupineWakeWordDetector(WakeWordDetector):
    def __init__(self, settings: VoiceSettings) -> None:
        if not settings.porcupine_access_key:
            raise RuntimeError(
                "Porcupine wake-word backend selected but PORCUPINE_ACCESS_KEY is not set."
            )
        self._settings = settings

    def listen(self, stop_event: threading.Event) -> bool:
        try:
            import pvporcupine
        except ImportError as exc:
            raise RuntimeError(
                "pvporcupine is not installed. Install it with: pip install pvporcupine"
            ) from exc

        keyword_paths = (
            [self._settings.porcupine_keyword_path]
            if self._settings.porcupine_keyword_path
            else None
        )
        porcupine = pvporcupine.create(
            access_key=self._settings.porcupine_access_key,
            keyword_paths=keyword_paths,
            keywords=None if keyword_paths else ["jarvis"],
        )
        sd = require_sounddevice()
        try:
            with sd.RawInputStream(
                samplerate=porcupine.sample_rate,
                blocksize=porcupine.frame_length,
                dtype="int16",
                channels=1,
            ) as stream:
                while not stop_event.is_set():
                    data, _overflowed = stream.read(porcupine.frame_length)
                    pcm = np.frombuffer(data, dtype=np.int16)
                    if porcupine.process(pcm) >= 0:
                        return True
            return False
        finally:
            porcupine.delete()


def get_wake_word_detector(settings: VoiceSettings) -> WakeWordDetector:
    if settings.wake_word_backend == "porcupine":
        return PorcupineWakeWordDetector(settings)
    return KeywordWakeWordDetector(settings)


_phrase_stt_by_size: dict[str, SpeechToText] = {}


def listen_for_phrases(
    settings: VoiceSettings,
    phrases: dict[str, str | tuple[str, ...]],
    stop_event: threading.Event,
    *,
    model_size: str | None = None,
) -> str | None:
    """STT-based multi-phrase listener, independent of whichever
    WakeWordDetector backend is actually configured — Porcupine is a fixed
    offline keyword engine and can't recognize an arbitrary user-chosen
    phrase at all, so the stop-word pause feature
    (core/voice/pipeline.py._wait_for_wake_or_pause) always uses this
    instead, listening for the wake word and the configured stop word in
    the same pass rather than polling the mic twice.

    `model_size` defaults to settings.whisper_wake_model_size (the fast
    "tiny" tier, same as the plain wake-word detector) but
    _wait_for_wake_or_pause passes the bigger command-tier model instead
    once a stop word is configured: the fixed wake word is a short, common,
    well-enunciated word chosen for how reliably "tiny" catches it, but a
    user-chosen stop word has no such guarantee (it can be an uncommon word,
    a phrase, or itself contain an anglicism) — under-recognizing it meant
    the pause command was silently ignored most of the time and only landed
    on a lucky transcription, which read as "doesn't understand the stop
    word at all, until suddenly it does and pauses". One instance is cached
    per model size (rather than one global) so switching between the two
    tiers across calls doesn't reload the model every time."""
    size = model_size or settings.whisper_wake_model_size
    stt = _phrase_stt_by_size.get(size)
    if stt is None:
        stt = SpeechToText(settings, model_size=size)
        _phrase_stt_by_size[size] = stt
    return _listen_for_any(stt, settings, phrases, stop_event)
