from __future__ import annotations

from modules.english_learning.domain import SubtitleCue
from modules.english_learning.word_selection import select_words
from tests.modules.english_learning.conftest import FakeLemmatizer


class _Cefr:
    levels = {("figure", "VERB"): "B1", ("decide", "VERB"): "A2", ("honest", "ADJ"): "B1", ("house", "NOUN"): "A1"}

    def level(self, lemma: str, pos: str) -> str | None:
        return self.levels.get((lemma, pos))


def _cues(*texts: str) -> list[SubtitleCue]:
    return [SubtitleCue(index=i + 1, start_ms=i * 1000, end_ms=i * 1000 + 900, text=text) for i, text in enumerate(texts)]


def test_keeps_a2_b1_words_and_drops_other_levels_names_stops_numbers() -> None:
    cues = _cues("I figured it out John.", "We decided 42 house.", "Walter is honest.")

    words = select_words(cues, FakeLemmatizer(), _Cefr())

    assert {(word.lemma, word.cefr, word.category) for word in words} == {
        ("figure", "B1", "core"),
        ("decide", "A2", "core"),
        ("honest", "B1", "core"),
    }


def test_frequent_unlisted_words_become_extra() -> None:
    cues = _cues("dude come on", "dude seriously", "yo dude")

    words = select_words(cues, FakeLemmatizer(), _Cefr())

    extra = [word for word in words if word.category == "extra"]
    assert [(word.lemma, word.count) for word in extra] == [("dude", 3)]


def test_rare_unlisted_words_are_dropped() -> None:
    words = select_words(_cues("dude once"), FakeLemmatizer(), _Cefr())

    assert all(word.lemma != "dude" for word in words)


def test_counts_occurrences_and_prefers_a_readable_example() -> None:
    cues = _cues("Figured.", "I figured you would come back to the house tonight.", "figured")

    words = select_words(cues, FakeLemmatizer(), _Cefr())

    figure = next(word for word in words if word.lemma == "figure")
    assert figure.count == 3
    assert figure.example == "I figured you would come back to the house tonight."
    assert figure.timestamp_ms == 1000
    assert figure.surface == "figured"


def test_long_examples_are_trimmed_around_the_word() -> None:
    long_line = " ".join(["word"] * 20) + " honest " + " ".join(["tail"] * 20)

    words = select_words(_cues(long_line), FakeLemmatizer(), _Cefr())

    honest = next(word for word in words if word.lemma == "honest")
    assert len(honest.example.split()) == 15
    assert "honest" in honest.example


def test_core_words_sort_before_extra() -> None:
    cues = _cues("dude figured", "dude", "dude")

    words = select_words(cues, FakeLemmatizer(), _Cefr())

    assert [word.category for word in words] == ["core", "extra"]
