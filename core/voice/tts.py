from __future__ import annotations

from typing import Any

import numpy as np

from core.logger import get_logger
from core.voice import audio_io
from core.voice import voice_preference
from core.voice.config import VoiceSettings
from core.voice.number_speech import spell_out_numbers
from core.voice.silero_tts import SAMPLE_RATE as SILERO_SAMPLE_RATE
from core.voice.silero_tts import (
    SileroVoice,
    resolve_silero_speaker,
    resolve_voice_pitch_shift,
    resolve_voice_prosody_rate,
)
from core.voice.sound_effects import BREATH_MARKER, generate_breath_sound
from core.voice.tts_effects import (
    apply_response_delay,
    robotic_voice_effect,
    tunnel_voice_effect,
)
from modules.user_profile import service_layer
from modules.user_profile.communication_styles import get_current_style
from modules.user_profile.domain import (
    ASSISTANT_VOLUME_KEY,
    BREATH_EFFECT_KEY,
    DELAY_EFFECT_ENABLED_KEY,
    DELAY_SECONDS_KEY,
    VOICE_FX_MODE_KEY,
)
from modules.user_profile.uow import ProfileUnitOfWork

logger = get_logger(__name__)

# Silence between the breath sound and the actual reply, so the two don't
# blend into one noise — long enough to read as a pause, short enough not
# to feel like a delay.
_BREATH_GAP_SECONDS = 0.08

_DEFAULT_DELAY_SECONDS = 0.3
_DEFAULT_ASSISTANT_VOLUME = 100


def _breath_effect_enabled() -> bool:
    return service_layer.get_fact(ProfileUnitOfWork(), BREATH_EFFECT_KEY) == "1"


def _apply_delay_if_enabled(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    if service_layer.get_fact(ProfileUnitOfWork(), DELAY_EFFECT_ENABLED_KEY) != "1":
        return samples
    raw_seconds = service_layer.get_fact(ProfileUnitOfWork(), DELAY_SECONDS_KEY)
    try:
        seconds = float(raw_seconds) if raw_seconds else _DEFAULT_DELAY_SECONDS
    except ValueError as corrupted_delay_setting:
        logger.debug(
            "Could not parse stored %s=%r, using default: %s",
            DELAY_SECONDS_KEY,
            raw_seconds,
            corrupted_delay_setting,
        )
        seconds = _DEFAULT_DELAY_SECONDS
    return apply_response_delay(samples, sample_rate, seconds)


def _apply_voice_fx(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    mode = service_layer.get_fact(ProfileUnitOfWork(), VOICE_FX_MODE_KEY)
    if mode == "tunnel":
        return tunnel_voice_effect(samples, sample_rate)
    if mode == "robotic":
        return robotic_voice_effect(samples, sample_rate)
    return samples


def get_assistant_volume() -> int:
    """The assistant's own TTS output gain (0-100), independent of the OS
    mixer level set via core/dispatcher.py's set_volume/change_volume."""
    raw = service_layer.get_fact(ProfileUnitOfWork(), ASSISTANT_VOLUME_KEY)
    if not raw:
        return _DEFAULT_ASSISTANT_VOLUME
    try:
        return max(0, min(100, int(raw)))
    except ValueError as corrupted_volume_setting:
        logger.debug(
            "Could not parse stored %s=%r, using default: %s", ASSISTANT_VOLUME_KEY, raw, corrupted_volume_setting
        )
        return _DEFAULT_ASSISTANT_VOLUME


def set_assistant_volume(percent: int) -> None:
    clamped = max(0, min(100, percent))
    service_layer.set_fact(ProfileUnitOfWork(), ASSISTANT_VOLUME_KEY, str(clamped))


def _apply_assistant_volume(samples: np.ndarray) -> np.ndarray:
    percent = get_assistant_volume()
    if percent == 100 or samples.size == 0:
        return samples
    return np.clip(samples * (percent / 100.0), -1.0, 1.0).astype(np.float32)


# WSOLA time-stretch parameters (see _time_stretch). A ~40ms frame at 50%
# overlap is the usual speech-friendly choice; the ±10ms waveform-similarity
# search between successive grains is what keeps them phase-aligned, so the
# result avoids the metallic "phasiness" plain overlap-add produces on
# voiced speech.
_STRETCH_FRAME_SECONDS = 0.040
_STRETCH_OVERLAP = 0.5
_STRETCH_SEEK_SECONDS = 0.010


def _linear_resample(samples: np.ndarray, target_length: int) -> np.ndarray:
    """Plain index-space resample — changes duration AND pitch together.
    Used only as the short-buffer fallback inside _time_stretch and as the
    second half of _apply_pitch_shift."""
    target_length = max(1, target_length)
    original_indices = np.arange(samples.size, dtype=np.float64)
    resampled_indices = np.linspace(0, samples.size - 1, target_length)
    return np.interp(resampled_indices, original_indices, samples).astype(np.float32)


def _time_stretch(samples: np.ndarray, sample_rate: int, stretch: float) -> np.ndarray:
    """Changes a waveform's duration by `stretch` (>1.0 longer/slower, <1.0
    shorter/faster) WITHOUT moving its pitch, via WSOLA: overlap-add of
    windowed grains, each nudged by a short cross-correlation search so it
    lines up with the previous one. Pure numpy — no scipy/librosa, matching
    the rest of this module's DSP. Buffers too short for a couple of frames
    fall back to a plain resample (a blip's pitch is inaudible anyway)."""
    samples = samples.astype(np.float32, copy=False)
    if stretch == 1.0 or samples.size == 0 or sample_rate <= 0:
        return samples

    frame = max(2, int(sample_rate * _STRETCH_FRAME_SECONDS))
    frame -= frame % 2
    syn_hop = max(1, int(frame * _STRETCH_OVERLAP))
    ana_hop = max(1, int(round(syn_hop / stretch)))
    seek = min(int(sample_rate * _STRETCH_SEEK_SECONDS), syn_hop)

    if samples.size < 2 * frame + seek:
        return _linear_resample(samples, int(round(samples.size * stretch)))

    window = np.hanning(frame).astype(np.float32)
    out_len = max(1, int(round(samples.size * stretch)))
    out = np.zeros(out_len + frame, dtype=np.float32)
    norm = np.zeros(out_len + frame, dtype=np.float32)
    max_start = samples.size - frame

    ana = 0.0
    syn = 0
    delta = 0
    while syn + frame <= out_len:
        start = min(max(int(ana) + delta, 0), max_start)
        out[syn:syn + frame] += samples[start:start + frame] * window
        norm[syn:syn + frame] += window

        reference = samples[start + syn_hop:start + syn_hop + frame]

        ana += ana_hop
        syn += syn_hop

        nominal = int(ana)
        if reference.size == frame and nominal - seek >= 0 and nominal + frame + seek <= samples.size:
            search = samples[nominal - seek:nominal + frame + seek]
            scores = np.correlate(search, reference, mode="valid")
            delta = int(np.argmax(scores)) - seek
        else:
            delta = 0

    out = out[:out_len]
    norm = norm[:out_len]
    np.divide(out, norm, out=out, where=norm > 1e-6)
    return out.astype(np.float32)


def _apply_prosody_rate(samples: np.ndarray, rate: float, sample_rate: int = SILERO_SAMPLE_RATE) -> np.ndarray:
    """Applies a communication style's tempo: rate > 1.0 speeds speech up,
    rate < 1.0 slows it down, 1.0 leaves it untouched. Pitch is preserved
    (unlike the old plain-resample approach, which also dragged the voice
    into an unnaturally low register whenever a calm/slow style was
    selected) — see _time_stretch. Neither Silero's apply_tts() nor Piper's
    synthesize() exposes a real prosody parameter, so this is still a
    stylized tempo shift, not genuine emotional delivery, but tempo and
    pitch are now independent."""
    if rate == 1.0 or samples.size == 0:
        return samples
    return _time_stretch(samples, sample_rate, 1.0 / rate)


def _apply_pitch_shift(samples: np.ndarray, sample_rate: int, ratio: float) -> np.ndarray:
    """Shifts a voice's pitch by `ratio` (e.g. 0.84 -> noticeably deeper,
    1.08 -> a touch brighter) while keeping its duration: resample to move
    the pitch (which also drags the duration by 1/ratio), then WSOLA-stretch
    back to the original length with the new pitch preserved. This is how
    the per-voice character variants (see core/voice/silero_tts.py) get a
    distinct timbre now that the old plain-resample trick — which also
    warped their tempo — is gone."""
    if ratio == 1.0 or samples.size == 0 or sample_rate <= 0:
        return samples
    repitched = _linear_resample(samples, int(round(samples.size / ratio)))
    restored = _time_stretch(repitched, sample_rate, ratio)
    if restored.size < 2:
        return samples.astype(np.float32, copy=False)
    return restored.astype(np.float32, copy=False)


class TextToSpeech:
    def __init__(self, settings: VoiceSettings) -> None:
        self._settings = settings
        self._voices: dict[str, Any] = {}
        self._silero: SileroVoice | None = None
        self._silero_failed = False

    def _get_silero(self) -> SileroVoice | None:
        """Silero gives noticeably more natural Russian speech than the
        available Piper voice; used for 'ru' whenever its weights are
        present (see VoiceSettings.silero_ru_model_path), with Piper as the
        fallback — for other languages, and if Silero errors out at runtime
        (_silero_failed latches that so a broken checkpoint doesn't retry
        and fail on every single reply)."""
        if self._silero_failed:
            return None
        if self._silero is None:
            if not self._settings.silero_ru_model_path.exists():
                return None
            self._silero = SileroVoice(
                self._settings.silero_ru_model_path, speaker=self._settings.silero_ru_speaker
            )
        return self._silero

    def _resolve_voice_language(self, language: str) -> str:
        """Pick the Piper voice to actually use for `language`, falling back to
        `fallback_language` (with a warning) when no model is configured or the
        configured model file is missing on disk."""
        model_path = self._settings.piper_voice_models.get(language)
        if model_path is not None and model_path.exists():
            return language

        if language not in self._settings.piper_voice_models:
            logger.warning(
                "No Piper voice configured for language '%s'; falling back to '%s'",
                language,
                self._settings.fallback_language,
            )
        else:
            logger.warning(
                "Piper voice model for '%s' not found at %s; falling back to '%s'",
                language,
                model_path,
                self._settings.fallback_language,
            )

        fallback = self._settings.fallback_language
        fallback_path = self._settings.piper_voice_models.get(fallback)
        if fallback_path is None or not fallback_path.exists():
            raise RuntimeError(
                f"No usable Piper voice for '{language}' and fallback language "
                f"'{fallback}' is not available either. Download a Piper .onnx voice "
                "and configure it in VoiceSettings.piper_voice_models."
            )
        return fallback

    def _get_voice(self, language: str) -> Any:
        resolved = self._resolve_voice_language(language)

        if resolved not in self._voices:
            model_path = self._settings.piper_voice_models[resolved]
            try:
                from piper.voice import PiperVoice
            except ImportError as exc:
                raise RuntimeError(
                    "piper-tts is not installed. Install it with: pip install piper-tts"
                ) from exc
            self._voices[resolved] = PiperVoice.load(str(model_path))

        return self._voices[resolved]

    def synthesize(self, text: str, language: str, speaker: str | None = None) -> tuple[np.ndarray, int]:
        """`speaker`, if given, overrides the persisted voice choice for this
        call only (used for one-off previews); otherwise the current
        selection from core.voice.voice_preference is used.

        Whatever comes out of Silero/Piper is then run through two
        independent, pitch-preserving steps: the communication style's tempo
        combined with the selected voice's own intrinsic tempo
        (`_apply_prosody_rate`), then that voice's intrinsic pitch shift
        (`_apply_pitch_shift`) — see modules.user_profile.communication_styles
        and core/voice/silero_tts.py's voice character variants. This is the
        "нейронка молчаливо разговаривает по-разному в зависимости от
        характера" bit; tempo and timbre are decoupled rather than warped
        together, but it is still a stylized shift, not real emotional
        delivery.

        If the breath effect is enabled AND `text` actually contains
        BREATH_MARKER (see core/voice/ai_router.py — the model itself
        decides per-reply whether one belongs, and where), the sound is
        spliced in at that exact position instead of always being prepended
        before the whole reply. No marker in the text means no sound at
        all for that reply, even with the setting on — it's the model's
        call, not an unconditional per-reply effect.

        Numbers in `text` are spelled out as words before either engine
        ever sees them (see number_speech.spell_out_numbers's own
        docstring for the live-found bug this fixes — Silero silently
        dropping/crashing on bare digits) — done once here, ahead of the
        breath-marker split below, so a marker sitting right next to a
        number isn't affected by the substitution changing string
        offsets."""
        text = spell_out_numbers(text, language)
        style = get_current_style()
        resolved_speaker = speaker or voice_preference.get_selected_speaker()
        voice_rate = resolve_voice_prosody_rate(resolved_speaker)
        voice_pitch = resolve_voice_pitch_shift(resolved_speaker)
        effective_rate = style.prosody_rate * voice_rate

        if _breath_effect_enabled() and BREATH_MARKER in text:
            samples, sample_rate = self._synthesize_with_breath_markers(text, language, speaker, effective_rate)
        else:
            samples, sample_rate = self._synthesize_raw(text, language, speaker)
            samples = _apply_prosody_rate(samples, effective_rate, sample_rate)

        samples = _apply_pitch_shift(samples, sample_rate, voice_pitch)
        samples = _apply_delay_if_enabled(samples, sample_rate)
        samples = _apply_voice_fx(samples, sample_rate)
        samples = _apply_assistant_volume(samples)
        return samples, sample_rate

    def _synthesize_with_breath_markers(
        self, text: str, language: str, speaker: str | None, effective_rate: float
    ) -> tuple[np.ndarray, int]:
        segments = [segment.strip() for segment in text.split(BREATH_MARKER)]
        pieces: list[np.ndarray] = []
        sample_rate = SILERO_SAMPLE_RATE
        have_sample_rate = False

        for index, segment in enumerate(segments):
            if segment:
                raw_samples, sr = self._synthesize_raw(segment, language, speaker)
                if not have_sample_rate:
                    sample_rate = sr
                    have_sample_rate = True
                pieces.append(_apply_prosody_rate(raw_samples, effective_rate, sr))
            if index < len(segments) - 1:
                breath = generate_breath_sound(sample_rate)
                if breath.size:
                    gap = np.zeros(int(sample_rate * _BREATH_GAP_SECONDS), dtype=np.float32)
                    pieces.append(breath)
                    pieces.append(gap)

        if not pieces:
            return np.zeros(0, dtype=np.float32), sample_rate
        return np.concatenate(pieces), sample_rate

    def _synthesize_raw(self, text: str, language: str, speaker: str | None) -> tuple[np.ndarray, int]:
        if language == "ru":
            silero = self._get_silero()
            if silero is not None:
                try:
                    public_speaker = speaker or voice_preference.get_selected_speaker()
                    return silero.synthesize(text, speaker=resolve_silero_speaker(public_speaker))
                except Exception:
                    logger.exception("Silero synthesis failed; falling back to Piper for the rest of this run")
                    self._silero_failed = True

        voice = self._get_voice(language)
        chunks = list(voice.synthesize(text))
        if not chunks:
            return np.zeros(0, dtype=np.float32), voice.config.sample_rate
        samples = np.concatenate([chunk.audio_float_array for chunk in chunks])
        sample_rate = chunks[0].sample_rate
        return samples, sample_rate

    def speak(self, text: str, language: str, speaker: str | None = None) -> None:
        samples, sample_rate = self.synthesize(text, language, speaker=speaker)
        audio_io.play_audio(samples, sample_rate)
