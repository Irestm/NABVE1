from __future__ import annotations

import pytest

from modules.english_learning.domain import SubtitleCue
from modules.english_learning.lemmatizer import SpacyLemmatizer
from modules.english_learning.word_selection import select_words

spacy = pytest.importorskip("spacy")
if not spacy.util.is_package("en_core_web_sm"):
    pytest.skip("en_core_web_sm is not installed", allow_module_level=True)


class _Cefr:
    def level(self, lemma: str, pos: str) -> str | None:
        return {"figure": "B1", "decide": "A2", "honest": "B1"}.get(lemma)


def test_real_spacy_lemmatizes_and_drops_names() -> None:
    cues = [
        SubtitleCue(1, 0, 1000, "I figured it out, Walter."),
        SubtitleCue(2, 1000, 2000, "Jesse decided to be honest with Walter."),
    ]

    words = select_words(cues, SpacyLemmatizer(), _Cefr())

    lemmas = {word.lemma for word in words}
    assert {"figure", "decide", "honest"} <= lemmas
    assert "walter" not in lemmas and "jesse" not in lemmas
