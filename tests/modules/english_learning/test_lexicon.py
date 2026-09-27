from __future__ import annotations

import json

from modules.english_learning.lexicon import classify_entry, entries_from_jsonl


def _entry(word: str, pos: str, tags: list[str], etymology: list[tuple[str, str]] | None = None) -> dict[str, object]:
    return {
        "word": word,
        "pos": pos,
        "lang_code": "en",
        "senses": [{"tags": tags, "glosses": ["x"]}],
        "etymology_templates": [{"name": name, "args": {"2": lang}} for name, lang in (etymology or [])],
    }


def test_derived_etymology_does_not_drop_english_idioms() -> None:
    entry = _entry("break a leg", "intj", ["idiomatic"], [("unk", ""), ("der", "yi"), ("der", "de")])

    assert classify_entry(entry) == "idiom"


def test_foreign_borrowings_and_function_word_pairs_are_skipped() -> None:
    assert classify_entry(_entry("absque hoc", "phrase", [], [("learned borrowing", "la")])) is None
    assert classify_entry(_entry("tant pis", "phrase", [], [("bor", "fr")])) is None
    assert classify_entry(_entry("of an", "phrase", [])) is None


def test_phrasal_verbs_slang_and_obsolete_senses() -> None:
    assert classify_entry(_entry("give up", "verb", [])) == "phrasal_verb"
    assert classify_entry(_entry("run out of", "verb", [])) == "phrasal_verb"
    assert classify_entry(_entry("what's up", "phrase", ["slang"])) == "slang"
    assert classify_entry(_entry("give sb the slip", "verb", ["obsolete"])) is None
    assert classify_entry(_entry("Big Apple", "phrase", ["idiomatic"])) is None


def test_entries_from_jsonl_normalizes() -> None:
    lines = [json.dumps(_entry("Wrap  up", "verb", [])), "not json", json.dumps(_entry("wrap up", "verb", []))]

    assert [(item.normalized, item.kind) for item in entries_from_jsonl(lines)] == [("wrap up", "phrasal_verb")]
