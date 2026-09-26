from __future__ import annotations

import pytest

from modules.english_learning.srt_parser import SrtParseError, clean_line, decode_srt, format_timestamp, parse_srt

SAMPLE = """1
00:00:01,500 --> 00:00:03,000
<i>I figured it out.</i>

2
00:01:02,040 --> 00:01:04,100
- WALTER: We decided.
- [door slams] Yeah?

3
00:01:05,000 --> 00:01:06,000
♪ la la la ♪

4
01:00:00.5 --> 01:00:01.000
{\\an8}Honest house.
"""


def test_parse_srt_extracts_cleaned_cues_and_times() -> None:
    cues = parse_srt(SAMPLE)

    assert [cue.text for cue in cues] == ["I figured it out.", "We decided. Yeah?", "Honest house."]
    assert cues[0].start_ms == 1500
    assert cues[0].end_ms == 3000
    assert cues[1].start_ms == 62040
    assert cues[2].start_ms == 3_600_500
    assert [cue.index for cue in cues] == [1, 2, 3]


def test_parse_srt_handles_windows_newlines_and_bom() -> None:
    cues = parse_srt("﻿1\r\n00:00:01,000 --> 00:00:02,000\r\nHello there\r\n\r\n")

    assert cues[0].text == "Hello there"


def test_parse_srt_rejects_text_without_cues() -> None:
    with pytest.raises(SrtParseError):
        parse_srt("just some text")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<font color=red>Hi</font>", "Hi"),
        ("(laughs) Okay", "Okay"),
        ("JESSE: Yo", "Yo"),
        ("-  spaced   out ", "spaced out"),
    ],
)
def test_clean_line(raw: str, expected: str) -> None:
    assert clean_line(raw) == expected


def test_decode_srt_supports_legacy_encodings() -> None:
    raw = "1\n00:00:01,000 --> 00:00:02,000\nCafé\n".encode("cp1252")

    assert "Café" in decode_srt(raw)


def test_decode_srt_rejects_non_subtitles() -> None:
    with pytest.raises(SrtParseError):
        decode_srt(b"not a subtitle file")


def test_format_timestamp() -> None:
    assert format_timestamp(3_723_456) == "01:02:03"
