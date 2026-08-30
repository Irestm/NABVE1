from __future__ import annotations

import pytest

from modules.multi_command_parser import split_commands


def test_no_separator_returns_text_unchanged() -> None:
    assert split_commands("поставь таймер на пять минут", "ru") == ["поставь таймер на пять минут"]


def test_empty_text() -> None:
    assert split_commands("   ", "ru") == [""]


def test_splits_on_i_conjunction_ru() -> None:
    assert split_commands("выключи звук и сверни окно", "ru") == ["выключи звук", "сверни окно"]


def test_splits_on_comma_ru() -> None:
    assert split_commands("открой браузер, поставь яркость 50", "ru") == [
        "открой браузер",
        "поставь яркость 50",
    ]


def test_splits_on_potom_and_strips_leading_connective() -> None:
    assert split_commands("сверни окно а потом заблокируй экран", "ru") == [
        "сверни окно",
        "заблокируй экран",
    ]


def test_three_way_split() -> None:
    assert split_commands("выключи звук, сверни окно и заблокируй экран", "ru") == [
        "выключи звук",
        "сверни окно",
        "заблокируй экран",
    ]


def test_short_tail_fragment_collapses_to_single_command() -> None:
    # "музыку" alone is not a command — do not cut a noun tail off the verb.
    assert split_commands("выключи свет и музыку", "ru") == ["выключи свет и музыку"]


def test_single_word_pair_is_not_split() -> None:
    assert split_commands("громче и ярче", "ru") == ["громче и ярче"]


def test_conjunction_inside_a_word_does_not_split() -> None:
    assert split_commands("иди на кухню", "ru") == ["иди на кухню"]


def test_ukrainian_separators() -> None:
    assert split_commands("вимкни звук і згорни вікно", "uk") == ["вимкни звук", "згорни вікно"]


def test_english_then_separator() -> None:
    assert split_commands("mute the sound then lock my screen", "en") == [
        "mute the sound",
        "lock my screen",
    ]


def test_english_and_separator() -> None:
    assert split_commands("open the browser and minimize the window", "en") == [
        "open the browser",
        "minimize the window",
    ]


@pytest.mark.parametrize(
    "text",
    [
        "открой ютуб и найди видео про котиков",
        "создай папку отчёты и перемести туда файл",
    ],
)
def test_realistic_two_command_phrases_split(text: str) -> None:
    assert len(split_commands(text, "ru")) == 2
