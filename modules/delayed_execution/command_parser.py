from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

# One universal "run this later" parser, applied to the whole utterance
# before it is classified as any particular command — "открой браузер через
# 10 минут", "выключи компьютер через час", "напомни позвонить в 18 часов".

_UNIT_SECONDS: tuple[tuple[str, int], ...] = (
    ("сек", 1), ("second", 1),
    ("мин", 60), ("хвилин", 60), ("minute", 60),
    ("час", 3600), ("годин", 3600), ("hour", 3600),
)

# "через <N> <unit>" / "за <N> <unit>" / "in <N> <unit>". The number is
# optional so "через час" / "через минуту" / "через полчаса" also parse.
_RELATIVE_RE = re.compile(
    r"\b(?:через|за|спустя|in|after)\s+"
    r"(?:(?P<num>\d+)\s+)?"
    r"(?P<word>полчаса|полминуты|"
    r"секунд\w*|сек|минут\w*|мин|хвилин\w*|"
    r"час(?:а|ов)?|годин\w*|"
    r"seconds?|minutes?|hours?)\b",
    re.IGNORECASE,
)

# "в 18 часов" / "о 9 годині" (uk) / "at 18" — deliberately requires the
# hour word (or English "at") so "поставь громкость в 20 процентов" and
# "открой файл в 2 колонки" don't read as a clock time.
_ABSOLUTE_RE = re.compile(
    r"\b(?:в|о)\s+(?P<hh>[01]?\d|2[0-3])(?:[:.](?P<mm>[0-5]\d))?\s+(?:час(?:ов|а)?|годин\w*)"
    r"|\bat\s+(?P<hh2>[01]?\d|2[0-3])(?:[:.](?P<mm2>[0-5]\d))?\b",
    re.IGNORECASE,
)

_WORD_SECONDS: dict[str, int] = {"полчаса": 1800, "полминуты": 30}


@dataclass(frozen=True)
class DelaySpec:
    run_at: datetime
    remainder: str
    spoken_delay: str


def _unit_seconds(word: str) -> int:
    lowered = word.lower()
    if lowered in _WORD_SECONDS:
        return _WORD_SECONDS[lowered]
    for prefix, seconds in _UNIT_SECONDS:
        if lowered.startswith(prefix):
            return seconds
    return 0


def _humanize(seconds: int) -> str:
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return "час" if hours == 1 else f"{hours} ч"
    if seconds % 60 == 0:
        return f"{seconds // 60} мин"
    return f"{seconds} с"


def _strip_span(text: str, span: tuple[int, int]) -> str:
    joined = f"{text[: span[0]]} {text[span[1] :]}"
    return re.sub(r"\s{2,}", " ", joined).strip(" ,.;—-")


def extract_delay(text: str, language: str, *, now: datetime | None = None) -> DelaySpec | None:
    """Pulls a time marker out of `text` and returns when to run whatever is
    left, or None when there is no marker (or nothing is left once it is
    removed). A relative marker ("через 10 минут") wins over an absolute one
    ("в 18 часов") if both appear."""
    reference = now or datetime.now()

    relative = _RELATIVE_RE.search(text)
    if relative is not None:
        unit_seconds = _unit_seconds(relative.group("word"))
        count = int(relative.group("num")) if relative.group("num") else 1
        total_seconds = unit_seconds * count if relative.group("num") else (unit_seconds or 0)
        if unit_seconds and total_seconds > 0:
            remainder = _strip_span(text, relative.span())
            if remainder:
                return DelaySpec(
                    run_at=reference + timedelta(seconds=total_seconds),
                    remainder=remainder,
                    spoken_delay=_humanize(total_seconds),
                )
        return None

    absolute = _ABSOLUTE_RE.search(text)
    if absolute is not None:
        hour = int(absolute.group("hh") or absolute.group("hh2"))
        minute = int(absolute.group("mm") or absolute.group("mm2") or 0)
        target = reference.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= reference:
            target += timedelta(days=1)
        remainder = _strip_span(text, absolute.span())
        if remainder:
            return DelaySpec(run_at=target, remainder=remainder, spoken_delay=f"в {hour:02d}:{minute:02d}")
    return None
