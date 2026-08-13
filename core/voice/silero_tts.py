from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

# Weights: Silero's own model.silero.ai host isn't reachable from every
# network; a working mirror of the multi-speaker v3_1_ru checkpoint is at
# https://huggingface.co/imperialwool/silero-model-v3-ru/resolve/main/model.pt
# — download it to data/voices/silero_ru_v3.pt (see VoiceSettings.silero_ru_model_path).
DEFAULT_SPEAKER = "eugene"
SAMPLE_RATE = 48000


@dataclass(frozen=True)
class VoiceOption:
    # `speaker` is the public, selectable/persisted identity (what's stored
    # in voice_preference.json and shown in the UI) — not necessarily a real
    # Silero speaker name; see `silero_speaker`.
    speaker: str
    label: str
    gender: str
    # The actual Silero speaker to pass to apply_tts(). Defaults to
    # `speaker` when empty — only differs for the pitch/tempo *variants*
    # below, which reuse a real speaker's voice but aren't a distinct
    # identity Silero itself knows about. Resolve via resolve_silero_speaker().
    silero_speaker: str = ""
    # Intrinsic tempo/pitch multiplier for this specific voice entry (see
    # core/voice/tts.py:_apply_prosody_rate), independent of and combined
    # with whatever the current communication style's own rate is. 1.0 for
    # every real distinct speaker; only the variants below set this.
    prosody_rate: float = 1.0


# The five named speakers shipped in the v3_1_ru multi-speaker checkpoint,
# "random" as an explicit sixth option (the model answers to it too, but
# it isn't a stable identity — every synthesize() call gets a different
# random voice rather than sticking to one; exposed on purpose, with the
# instability spelled out in the label itself), plus three pitch/tempo
# *variants* built on top of the three most distinct real speakers. Those
# three aren't new Silero speaker identities — there are only ever the five
# real ones in this checkpoint — they're the same underlying voice resampled
# to a deliberately different tempo/pitch (see resolve_silero_speaker /
# resolve_voice_prosody_rate and core/voice/tts.py), a second, honest way to
# add more *selectable, audibly distinct* options without pretending a 6th
# person exists in the model.
VOICE_OPTIONS: tuple[VoiceOption, ...] = (
    VoiceOption(speaker="aidar", label="Айдар", gender="male"),
    VoiceOption(speaker="aidar-deep", label="Айдар низкий", gender="male", silero_speaker="aidar", prosody_rate=0.85),
    VoiceOption(speaker="eugene", label="Евгений", gender="male"),
    VoiceOption(
        speaker="eugene-bright", label="Евгений бодрый", gender="male", silero_speaker="eugene", prosody_rate=1.15
    ),
    VoiceOption(speaker="baya", label="Байя", gender="female"),
    VoiceOption(speaker="baya-soft", label="Байя мягкая", gender="female", silero_speaker="baya", prosody_rate=0.92),
    VoiceOption(speaker="kseniya", label="Ксения", gender="female"),
    # Labeled "Вторая Ксения", not just "Ксения (Xenia)": onboarding's
    # spoken voice selection (modules/user_profile/onboarding.py's
    # _voice_short_name) strips everything from " (" onward, so "Ксения
    # (Xenia)" and plain "Ксения" collapsed to the identical short name
    # "Ксения" — this voice could never actually be chosen by voice, only
    # "kseniya" ever matched. The first word now has to differ. Same reason
    # the three variants above are named "Айдар низкий" etc without
    # parentheses, not "Айдар (низкий)".
    VoiceOption(speaker="xenia", label="Вторая Ксения (Xenia)", gender="female"),
    VoiceOption(speaker="random", label="Случайный (звучит по-разному каждый раз)", gender="other"),
)
VOICE_SPEAKER_IDS: frozenset[str] = frozenset(option.speaker for option in VOICE_OPTIONS)

_SILERO_SPEAKER_BY_OPTION: dict[str, str] = {
    option.speaker: (option.silero_speaker or option.speaker) for option in VOICE_OPTIONS
}
_PROSODY_RATE_BY_OPTION: dict[str, float] = {option.speaker: option.prosody_rate for option in VOICE_OPTIONS}


def resolve_silero_speaker(speaker: str) -> str:
    """The real Silero speaker name to pass to apply_tts() for a given
    *public* voice id — identical for the five real speakers and "random",
    and mapped back to the underlying real speaker for a pitch/tempo variant
    (e.g. "aidar-deep" -> "aidar")."""
    return _SILERO_SPEAKER_BY_OPTION.get(speaker, speaker)


def resolve_voice_prosody_rate(speaker: str) -> float:
    """This voice option's own intrinsic tempo/pitch multiplier (1.0 for
    every real speaker; only the variants differ) — combined with the
    current communication style's rate in core/voice/tts.py, not a
    replacement for it."""
    return _PROSODY_RATE_BY_OPTION.get(speaker, 1.0)


class SileroVoice:
    """A single loaded Silero TTS checkpoint (a torch.package archive, not a
    plain state dict — hence PackageImporter rather than torch.load).
    Loaded lazily on first synthesize() call, then cached for the process's
    lifetime, matching TextToSpeech's own lazy-per-language voice loading.

    The checkpoint is multi-speaker (see VOICE_OPTIONS), so the speaker is
    passed per synthesize() call rather than baked in at construction —
    that lets callers switch voices (or preview one without switching the
    default) without reloading the model."""

    def __init__(self, model_path: Path, speaker: str = DEFAULT_SPEAKER, sample_rate: int = SAMPLE_RATE) -> None:
        self._model_path = model_path
        self._speaker = speaker
        self._sample_rate = sample_rate
        self._model: Any | None = None

    def _get_model(self) -> Any:
        if self._model is None:
            import torch

            torch.set_num_threads(4)
            importer = torch.package.PackageImporter(str(self._model_path))
            self._model = importer.load_pickle("tts_models", "model")
        return self._model

    def synthesize(self, text: str, speaker: str | None = None) -> tuple[np.ndarray, int]:
        model = self._get_model()
        audio = model.apply_tts(text=text, speaker=speaker or self._speaker, sample_rate=self._sample_rate)
        return audio.numpy().astype(np.float32), self._sample_rate
