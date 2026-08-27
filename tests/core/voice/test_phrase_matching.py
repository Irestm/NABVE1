from __future__ import annotations

from core.voice.phrase_matching import fuzzy_contains_phrase, fuzzy_matches_any, with_transliterated_variant


def test_matches_single_word_phrase() -> None:
    assert fuzzy_contains_phrase("ассистент привет", "ассистент")


def test_matches_multi_word_phrase() -> None:
    assert fuzzy_contains_phrase("ну хватит уже болтать", "хватит уже")


def test_tolerates_minor_stt_noise() -> None:
    assert fuzzy_contains_phrase("ассистэнт", "ассистент")


def test_does_not_match_unrelated_text() -> None:
    assert not fuzzy_contains_phrase("какая сегодня погода", "хватит уже")


def test_empty_phrase_never_matches() -> None:
    assert not fuzzy_contains_phrase("что угодно", "")


def test_matches_any_finds_a_word_buried_in_a_longer_sentence() -> None:
    # The motivating case: a shutdown/restart confirmation like "да, давай,
    # выключай" should still count as "да" was said, not just a bare "да".
    assert fuzzy_matches_any("да, давай, выключай", {"да", "подтверждаю", "согласен"})


def test_matches_any_false_when_nothing_present() -> None:
    assert not fuzzy_matches_any("нет, не надо", {"да", "подтверждаю", "согласен"})


def test_short_utterance_matches_the_key_word_of_a_longer_stored_phrase() -> None:
    # Regression: a stop word saved as a full sentence during setup
    # ("пусть будет тишина") used to be impossible to ever trigger by just
    # saying the one word that mattered ("тишина") - the window was always
    # sized to the *stored* phrase's word count, so a shorter utterance
    # could never produce even one full-length window to compare.
    assert fuzzy_contains_phrase("тишина", "пусть будет тишина")


def test_short_utterance_does_not_match_an_unrelated_longer_phrase() -> None:
    assert not fuzzy_contains_phrase("апельсин", "пусть будет тишина")


def test_single_word_still_matches_single_word_phrase_both_directions() -> None:
    assert fuzzy_contains_phrase("да", "да")
    assert not fuzzy_contains_phrase("нет", "да")


def test_yo_ye_orthographic_variants_match_each_other() -> None:
    # Regression: a stop word typed as "орел" (е, as most people type it)
    # against Whisper transcribing it back as "орёл" (ё, the grammatically
    # correct spelling) used to sit exactly at the similarity threshold for
    # a word this short - any additional real-world STT noise on top of the
    # missing diacritic would push it below and silently fail to match.
    assert fuzzy_contains_phrase("орёл", "орел")
    assert fuzzy_contains_phrase("орел", "орёл")
    assert fuzzy_contains_phrase("скажи орёл громко", "орел")


def test_transliterated_variant_lets_a_latin_transcription_of_a_stop_word_match() -> None:
    # Regression: Whisper's own language detection is unreliable on a short
    # word said in isolation - a stop word configured as "стоп" regularly
    # comes back transcribed as the Latin "Stop" instead. Character-level
    # SequenceMatcher never matched these (Cyrillic and Latin letters share
    # no codepoints even when they sound the same), so the stop word would
    # silently fail to register whenever STT flipped language mid-word.
    # fuzzy_contains_phrase itself is untouched (see the false-positive test
    # below) - callers fold in with_transliterated_variant's extra candidate
    # instead, exactly like core/voice/special_phrases.py does.
    assert fuzzy_matches_any("Stop", with_transliterated_variant("стоп"))
    assert fuzzy_matches_any("okay Stop now", with_transliterated_variant("стоп"))
    assert not fuzzy_contains_phrase("Stop", "стоп")  # unmodified — no transliteration built in


def test_transliterated_variant_is_unchanged_for_already_latin_phrases() -> None:
    assert with_transliterated_variant("stop") == ("stop",)


def test_transliteration_is_not_folded_into_the_shared_matchers_by_default() -> None:
    # Regression: an earlier version of this fix transliterated every
    # window inside fuzzy_contains_phrase itself. Multi-character mappings
    # (ж->zh, ш->sh, щ->shch) skew SequenceMatcher's length-based ratio just
    # enough to push unrelated same-script pairs like "включи"/"выключи"
    # over threshold, which broke youtube/spotify/shutdown trigger matching
    # (core/voice/intent.py) elsewhere in the app. fuzzy_contains_phrase and
    # fuzzy_matches_any must stay exactly as they always were.
    assert not fuzzy_contains_phrase("включи на ютубе лоу фай бит", "выключи компьютер")
