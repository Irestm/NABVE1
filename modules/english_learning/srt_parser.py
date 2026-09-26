from __future__ import annotations

import re

from modules.english_learning.domain import SubtitleCue

_TIMING = re.compile(
    r"(?P<h1>\d{1,2}):(?P<m1>\d{2}):(?P<s1>\d{2})[,.](?P<ms1>\d{1,3})\s*-->\s*"
    r"(?P<h2>\d{1,2}):(?P<m2>\d{2}):(?P<s2>\d{2})[,.](?P<ms2>\d{1,3})"
)
_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>|<\d{2}:\d{2}:\d{2}\.\d{3}>")
_ASS_TAG = re.compile(r"\{\\[^}]*\}")
_SOUND_NOTE = re.compile(r"\[[^\]]*\]|\([^)]*\)|♪[^♪]*♪|♪")
_SPEAKER_LABEL = re.compile(r"^\s*[A-Z][A-Z0-9 .'\-]{1,30}:\s*")
_LEADING_DASH = re.compile(r"^\s*[-–—]\s*")
_WHITESPACE = re.compile(r"\s+")


class SrtParseError(ValueError):
    pass


def decode_srt(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "-->" in text:
            return text
    raise SrtParseError("Файл не похож на субтитры .srt")


def _to_ms(hours: str, minutes: str, seconds: str, millis: str) -> int:
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis.ljust(3, "0"))


def clean_line(line: str) -> str:
    cleaned = _ASS_TAG.sub("", line)
    cleaned = _HTML_TAG.sub("", cleaned)
    cleaned = _SOUND_NOTE.sub(" ", cleaned)
    cleaned = _LEADING_DASH.sub("", cleaned)
    cleaned = _SPEAKER_LABEL.sub("", cleaned)
    return _WHITESPACE.sub(" ", cleaned).strip()


def parse_srt(text: str) -> list[SubtitleCue]:
    blocks = re.split(r"\r?\n\s*\r?\n", text.replace("﻿", "").strip())
    cues: list[SubtitleCue] = []
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        timing = next(((i, m) for i, line in enumerate(lines) if (m := _TIMING.search(line))), None)
        if timing is None:
            continue
        timing_index, match = timing
        body = " ".join(filter(None, (clean_line(line) for line in lines[timing_index + 1 :])))
        if not body:
            continue
        cues.append(
            SubtitleCue(
                index=len(cues) + 1,
                start_ms=_to_ms(match["h1"], match["m1"], match["s1"], match["ms1"]),
                end_ms=_to_ms(match["h2"], match["m2"], match["s2"], match["ms2"]),
                text=body,
            )
        )
    if not cues:
        raise SrtParseError("В файле не найдено ни одной реплики")
    return cues


def format_timestamp(ms: int) -> str:
    seconds, _ = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


_VTT_TIMING = re.compile(
    r"(?:(?P<h1>\d{1,2}):)?(?P<m1>\d{2}):(?P<s1>\d{2})\.(?P<ms1>\d{3})\s*-->\s*"
    r"(?:(?P<h2>\d{1,2}):)?(?P<m2>\d{2}):(?P<s2>\d{2})\.(?P<ms2>\d{3})"
)


def parse_vtt(text: str) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    previous_text = ""
    for block in re.split(r"\r?\n\s*\r?\n", text.replace("﻿", "").strip()):
        lines = [line for line in block.splitlines() if line.strip()]
        timing = next(((i, m) for i, line in enumerate(lines) if (m := _VTT_TIMING.search(line))), None)
        if timing is None:
            continue
        timing_index, match = timing
        body = " ".join(filter(None, (clean_line(line) for line in lines[timing_index + 1 :])))
        if not body:
            continue
        if previous_text and body.startswith(previous_text):
            body = body[len(previous_text) :].strip()
        if not body or body == previous_text:
            continue
        previous_text = body
        cues.append(
            SubtitleCue(
                index=len(cues) + 1,
                start_ms=_to_ms(match["h1"] or "0", match["m1"], match["s1"], match["ms1"]),
                end_ms=_to_ms(match["h2"] or "0", match["m2"], match["s2"], match["ms2"]),
                text=body,
            )
        )
    if not cues:
        raise SrtParseError("В субтитрах не найдено ни одной реплики")
    return cues


def _srt_time(ms: int) -> str:
    seconds, millis = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def cues_to_srt(cues: list[SubtitleCue]) -> str:
    return "\n".join(
        f"{number}\n{_srt_time(cue.start_ms)} --> {_srt_time(cue.end_ms)}\n{cue.text}\n"
        for number, cue in enumerate(cues, start=1)
    )
