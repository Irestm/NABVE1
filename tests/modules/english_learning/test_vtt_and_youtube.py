from __future__ import annotations

from modules.english_learning import youtube_subs
from modules.english_learning.srt_parser import cues_to_srt, parse_srt, parse_vtt

VTT = """WEBVTT
Kind: captions

00:00:01.000 --> 00:00:02.500
hello<00:00:01.500><c> there</c>

00:00:02.500 --> 00:00:04.000
hello there
how are you

00:01:04.000 --> 00:01:05.000
[Music]
"""


def test_parse_vtt_strips_inline_timing_and_rolling_duplicates() -> None:
    cues = parse_vtt(VTT)

    assert [cue.text for cue in cues] == ["hello there", "how are you"]
    assert cues[1].start_ms == 2500


def test_cues_round_trip_through_srt() -> None:
    cues = parse_vtt(VTT)

    again = parse_srt(cues_to_srt(cues))

    assert [(cue.text, cue.start_ms, cue.end_ms) for cue in again] == [
        (cue.text, cue.start_ms, cue.end_ms) for cue in cues
    ]


def test_pick_track_prefers_english_vtt() -> None:
    tracks = {
        "de": [{"ext": "vtt", "url": "de"}],
        "en-GB": [{"ext": "json3", "url": "json"}, {"ext": "vtt", "url": "gb"}],
        "en": [{"ext": "srv1", "url": "srv"}],
    }

    assert youtube_subs._pick_track(tracks) == "gb"
    assert youtube_subs._pick_track({"de": [{"ext": "vtt", "url": "x"}]}) is None
