from __future__ import annotations

from core.voice.silero_tts import (
    VOICE_OPTIONS,
    VOICE_SPEAKER_IDS,
    resolve_silero_speaker,
    resolve_voice_pitch_shift,
    resolve_voice_prosody_rate,
)


def test_nine_voices_are_offered() -> None:
    assert len(VOICE_OPTIONS) == 9


def test_voice_speaker_ids_are_unique() -> None:
    speakers = [option.speaker for option in VOICE_OPTIONS]
    assert len(speakers) == len(set(speakers))


def test_base_voice_resolves_to_itself() -> None:
    assert resolve_silero_speaker("aidar") == "aidar"
    assert resolve_voice_prosody_rate("aidar") == 1.0
    assert resolve_voice_pitch_shift("aidar") == 1.0


def test_variant_resolves_to_underlying_real_speaker() -> None:
    assert resolve_silero_speaker("aidar-deep") == "aidar"
    assert resolve_silero_speaker("eugene-bright") == "eugene"
    assert resolve_silero_speaker("baya-soft") == "baya"


def test_variant_has_a_distinct_timbre() -> None:
    # "Василич" / "Артём" are pitch-shifted (deeper / brighter) at normal
    # tempo; "Алиса" keeps her pitch but speaks a little slower.
    assert resolve_voice_pitch_shift("aidar-deep") < 1.0
    assert resolve_voice_prosody_rate("aidar-deep") == 1.0
    assert resolve_voice_pitch_shift("eugene-bright") > 1.0
    assert resolve_voice_prosody_rate("baya-soft") < 1.0
    assert resolve_voice_pitch_shift("baya-soft") == 1.0


def test_every_variant_differs_from_its_base_on_some_axis() -> None:
    for variant, base in (("aidar-deep", "aidar"), ("eugene-bright", "eugene"), ("baya-soft", "baya")):
        moved = (
            resolve_voice_pitch_shift(variant) != resolve_voice_pitch_shift(base)
            or resolve_voice_prosody_rate(variant) != resolve_voice_prosody_rate(base)
        )
        assert moved, variant


def test_unknown_speaker_resolves_to_itself_and_neutral_rate() -> None:
    assert resolve_silero_speaker("does-not-exist") == "does-not-exist"
    assert resolve_voice_prosody_rate("does-not-exist") == 1.0
    assert resolve_voice_pitch_shift("does-not-exist") == 1.0


def test_all_voice_labels_are_unique() -> None:
    labels = [option.label for option in VOICE_OPTIONS]
    assert len(labels) == len(set(labels))


def test_all_voice_speaker_ids_are_registered_for_persistence_validation() -> None:
    assert "aidar-deep" in VOICE_SPEAKER_IDS
    assert "eugene-bright" in VOICE_SPEAKER_IDS
    assert "baya-soft" in VOICE_SPEAKER_IDS
