from __future__ import annotations

import importlib.util

import pytest

from modules.english_learning.analysis import analyze_cues
from modules.english_learning.domain import SubtitleCue
from modules.english_learning.language_filter import LinguaDetector, classify, classify_cues
from modules.english_learning.srt_parser import clean_line, parse_srt
from tests.modules.english_learning.conftest import FakeDetector, FakeLemmatizer

SRT = """1
00:00:01,000 --> 00:00:03,000
<i>JESSE: I figured it out!</i>

2
00:00:04,000 --> 00:00:05,000
[music playing]

3
00:00:06,000 --> 00:00:07,000
(laughs) - We decided. - WALTER: Honest.

4
00:00:08,000 --> 00:00:09,000
♪ Baby, baby ♪
"""


class _Cefr:
    levels = {("figure", "VERB"): "B1", ("decide", "VERB"): "A2", ("honest", "ADJ"): "B1", ("house", "NOUN"): "A1"}

    def level(self, lemma: str, pos: str) -> str | None:
        return self.levels.get((lemma, pos))


def _cues(*texts: str) -> list[SubtitleCue]:
    return [SubtitleCue(index=i + 1, start_ms=i * 1000, end_ms=i * 1000 + 900, text=t) for i, t in enumerate(texts)]


def test_hearing_impaired_notes_and_speaker_names_are_removed() -> None:
    cues = parse_srt(SRT)

    assert [cue.text for cue in cues] == ["I figured it out!", "We decided. Honest."]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("MAN #2: Get out!", "Get out!"),
        ("*sighs* Fine.", "Fine."),
        (">> Hello there", "Hello there"),
        ("Tom &amp; Jerry", "Tom & Jerry"),
        ("At 10:30 we go.", "At 10:30 we go."),
        ("{\\an8}Up here", "Up here"),
    ],
)
def test_clean_line_variants(raw: str, expected: str) -> None:
    assert clean_line(raw) == expected


def test_spanish_lines_do_not_produce_words() -> None:
    cues = _cues("¿Dónde está el dinero, hermano? figured", "I decided to stay home.")

    analysis = analyze_cues(cues, FakeLemmatizer(), _Cefr(), detector=FakeDetector())

    assert analysis.languages.labels == ["foreign", "en"]
    assert {word.lemma for word in analysis.candidates} == {"decide"}
    assert analysis.languages.foreign_share == 0.5


def test_short_lines_are_not_dropped_by_language_only_unknown_words() -> None:
    cues = _cues("Vamos, honest!", "dude dude", "dude dude dude")

    analysis = analyze_cues(cues, FakeLemmatizer(), _Cefr(), detector=FakeDetector())

    assert analysis.languages.labels == ["short", "short", "en"]
    words = {word.lemma: word.count for word in analysis.candidates}
    assert words.get("honest") == 1
    assert "vamos" not in words
    assert words.get("dude") == 3


def test_short_line_classification_ignores_detector() -> None:
    class Never:
        def is_english(self, text: str) -> bool:
            raise AssertionError("short lines must not be sent to the detector")

    assert classify("Hola amigo", Never()) == "short"


@pytest.mark.skipif(importlib.util.find_spec("lingua") is None, reason="lingua-language-detector not installed")
def test_real_lingua_detects_spanish_lines() -> None:
    report = classify_cues(
        _cues("¿Dónde está el dinero, hermano?", "I figured it out, man.", "Nos vemos mañana en la casa."),
        LinguaDetector(),
    )

    assert report.labels == ["foreign", "en", "foreign"]
