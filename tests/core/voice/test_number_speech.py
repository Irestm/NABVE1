from __future__ import annotations

from core.voice.number_speech import spell_out_numbers


def test_spells_out_a_plain_integer() -> None:
    assert spell_out_numbers("22", "ru") == "двадцать два"


def test_spells_out_a_negative_integer() -> None:
    assert spell_out_numbers("-5", "ru") == "минус пять"


def test_spells_out_multiple_numbers_in_a_sentence() -> None:
    result = spell_out_numbers("температура от 12 до 22 градусов", "ru")
    assert result == "температура от двенадцать до двадцать два градусов"


def test_spells_out_percent_with_the_word_appended() -> None:
    assert spell_out_numbers("100%", "ru") == "сто процентов"


def test_spells_out_a_decimal_number() -> None:
    assert spell_out_numbers("12.5", "ru") == "двенадцать целых пять десятых"


def test_leaves_text_without_numbers_unchanged() -> None:
    text = "какая погода в киеве"
    assert spell_out_numbers(text, "ru") == text


def test_unsupported_language_leaves_text_unchanged() -> None:
    text = "22 degrees"
    assert spell_out_numbers(text, "xx") == text


def test_supports_english() -> None:
    assert spell_out_numbers("22", "en") == "twenty-two"


def test_supports_ukrainian() -> None:
    assert spell_out_numbers("5", "uk") == "п'ять"


def test_unconvertible_number_is_left_as_digits(monkeypatch) -> None:
    import core.voice.number_speech as number_speech_module

    def fake_num2words(value, lang):
        raise NotImplementedError("simulated")

    monkeypatch.setattr(number_speech_module, "num2words", fake_num2words)

    assert spell_out_numbers("22", "ru") == "22"
