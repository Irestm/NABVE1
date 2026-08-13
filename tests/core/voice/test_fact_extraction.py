from __future__ import annotations

from core.voice.fact_extraction import extract_facts


def test_extracts_name_and_location_as_separate_facts() -> None:
    facts = extract_facts("меня зовут Даниил и я живу в Киеве", "ru")
    by_key = {f.key: f.value for f in facts}
    assert by_key["name"] == "Даниил"
    assert by_key["location"] == "Киеве"


def test_extracts_english_name() -> None:
    facts = extract_facts("my name is Daniil and I live in Kyiv", "en")
    by_key = {f.key: f.value for f in facts}
    assert by_key["name"] == "Daniil"
    assert by_key["location"] == "Kyiv"


def test_unrelated_text_yields_no_facts() -> None:
    assert extract_facts("какая сегодня погода", "ru") == []


def test_unsupported_language_yields_no_facts() -> None:
    assert extract_facts("meu nome é Daniil", "pt") == []
