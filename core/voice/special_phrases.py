from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from core.voice import wake_word
from core.voice.config import VoiceSettings
from core.voice.phrase_matching import fuzzy_matches_any, with_transliterated_variant
from modules.tray_hide import detector as tray_hide_detector
from modules.tray_hide.config import HIDE_PHRASE_KEY, SHOW_PHRASE_KEY
from modules.user_profile import service_layer as profile_service_layer
from modules.user_profile.domain import STOP_WORD_KEY, WAKE_PHRASE_KEY
from modules.user_profile.uow import ProfileUnitOfWork


def _resolve_stop_word(settings: VoiceSettings) -> tuple[str, ...]:
    """Deliberately the user's own configured STOP_WORD_KEY only, never a
    fixed built-in word list — core/voice/intent.py's STOP_PHRASES/
    is_stop_command exists for two unrelated, narrower purposes (exiting
    OS-agent mode, a barge-in-during-confirmation nuance — see their own
    call sites in pipeline.py) and is intentionally left alone rather than
    reused here, so "pause"/"resume" always mean exactly the one phrase the
    user themselves picked in Настройки/Профиль, everywhere.

    with_transliterated_variant folds in a Latin-spelled candidate alongside
    the configured word — Whisper occasionally mistranscribes a short
    isolated word like "стоп" as the Latin "Stop" instead, which a plain
    Cyrillic-only comparison would never match — see its own docstring."""
    stop_word = profile_service_layer.get_fact(ProfileUnitOfWork(), STOP_WORD_KEY)
    return with_transliterated_variant(stop_word) if stop_word else ()


def _resolve_wake_phrases(settings: VoiceSettings) -> tuple[str, ...]:
    custom = profile_service_layer.get_fact(ProfileUnitOfWork(), WAKE_PHRASE_KEY)
    return wake_word.resolve_wake_phrases(settings, custom)


def _resolve_hide_phrases(settings: VoiceSettings) -> tuple[str, ...]:
    custom = profile_service_layer.get_fact(ProfileUnitOfWork(), HIDE_PHRASE_KEY)
    return tray_hide_detector.hide_phrases(custom)


def _resolve_show_phrases(settings: VoiceSettings) -> tuple[str, ...]:
    custom = profile_service_layer.get_fact(ProfileUnitOfWork(), SHOW_PHRASE_KEY)
    return tray_hide_detector.show_phrases(custom)


@dataclass(frozen=True)
class SpecialPhrase:
    key: str
    # Which pipeline states this phrase is listened for in: "idle" (waiting
    # for the wake word, see core/voice/pipeline.py._wait_for_wake_or_pause),
    # "paused" (waiting for the same word again to resume), "speaking"
    # (assistant mid-reply or mid-"thinking" — see core/voice/barge_in.py,
    # bracketed around every run_cancellable call, not just TTS playback),
    # "recording" (the user's own command is being captured — see
    # pipeline.py._record_command_audio, a second concurrent mic stream
    # alongside audio_io.record_until_silence's own).
    contexts: frozenset[str]
    resolve_variants: Callable[[VoiceSettings], tuple[str, ...]]


# Order is priority, shared by every context (previously only
# _wait_for_wake_or_pause's own dict got this right - see its docstring):
# "pause" must always win a race against "wake" when both fuzzy-match the
# same utterance (e.g. the stop word said in the same breath as the wake
# phrase, "привет стоп") - the default wake phrase "привет" alone can score
# a perfect substring match against it, and a stop word silently losing that
# race means it falls through as ordinary command text instead of pausing.
REGISTRY: tuple[SpecialPhrase, ...] = (
    SpecialPhrase("pause", frozenset({"idle", "speaking", "recording"}), _resolve_stop_word),
    SpecialPhrase("resume", frozenset({"paused"}), _resolve_stop_word),
    SpecialPhrase("wake", frozenset({"idle"}), _resolve_wake_phrases),
    SpecialPhrase("tray_hide", frozenset({"idle"}), _resolve_hide_phrases),
    SpecialPhrase("tray_show", frozenset({"idle"}), _resolve_show_phrases),
)


def variants_for_context(settings: VoiceSettings, context: str) -> dict[str, tuple[str, ...]]:
    """The {key: variants} mapping wake_word.listen_for_phrases (or any
    other STT-window-polling listener) expects for one context - e.g.
    _wait_for_wake_or_pause's "idle"/"paused" passes - built by filtering
    REGISTRY down to entries valid there and resolving each one's current
    variants (profile fact + defaults) fresh on every call, the same
    per-pass re-read _wait_for_wake_or_pause always did before this existed.
    A key with no variants right now (e.g. "pause" before any stop word is
    ever configured) is omitted rather than included with an empty tuple,
    so a caller can't accidentally end up fuzzy-matching against nothing.
    Dict insertion order follows REGISTRY, preserving the priority
    ordering callers like wake_word._listen_for_any rely on."""
    result: dict[str, tuple[str, ...]] = {}
    for entry in REGISTRY:
        if context not in entry.contexts:
            continue
        variants = entry.resolve_variants(settings)
        if variants:
            result[entry.key] = variants
    return result


def check(text: str, context: str, settings: VoiceSettings) -> str | None:
    """Matches already-transcribed `text` (as opposed to variants_for_context,
    which is for listening on a fresh mic window) against every REGISTRY
    entry valid for `context`, in priority order, returning the first key
    that fuzzy-matches - or None if nothing did. Used by
    core/voice/barge_in.py (context="speaking" or "recording", depending on
    what BargeInMonitor is bracketing) to recognize the user's own
    configured stop word, instead of the fixed STOP_PHRASES list it used to
    check there."""
    for entry in REGISTRY:
        if context not in entry.contexts:
            continue
        variants = entry.resolve_variants(settings)
        if variants and fuzzy_matches_any(text, variants):
            return entry.key
    return None
