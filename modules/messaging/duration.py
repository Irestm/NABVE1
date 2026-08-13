from __future__ import annotations

import re

# Fixed phrases that don't reduce to "<number> <unit>". Checked before the
# regex below (order matters only in that these short-circuit first — none
# of them overlap with a digit-led phrase anyway).
_FIXED_PHRASES: dict[str, int] = {
    "полчаса": 30,
    "пол часа": 30,
    "пару часов": 120,
    "пару минут": 5,
    "минутку": 1,
    "минуту": 1,
    "часок": 60,
    "час": 60,
}

_NUMBER_UNIT_PATTERN = re.compile(r"(\d+)\s*(минут\w*|мин\.?|час\w*|ч\.?)", re.IGNORECASE)
_HOUR_UNIT_PREFIXES = ("час", "ч")


def parse_duration_minutes(text: str) -> int | None:
    """Best-effort, deliberately non-AI parse of a spoken duration phrase
    ("10 минут", "полчаса", "час", "пару часов", ...) into a minute count.
    Returns None if nothing recognizable was found — the caller (see
    core/voice/pipeline.py._resolve_messaging_snooze) treats that as "не
    поняла" rather than retrying or escalating to an AI call: this is a
    narrow, mechanical phrase space (much closer to is_affirmative/
    is_stop_command than to modules/calendar/extraction.py's genuinely
    open-ended date parsing), so a second AI-backed attempt isn't
    warranted — nothing else in this codebase retries a failed clarifying
    question either."""
    normalized = text.strip().lower()
    if not normalized:
        return None

    # Digit-led phrases are checked first and take priority: a fixed phrase
    # like "час" is a plain substring of "часа", so "2 часа" would
    # otherwise match _FIXED_PHRASES["час"] (60) before the regex ever got
    # a chance to see the "2" and return the correct 120.
    match = _NUMBER_UNIT_PATTERN.search(normalized)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        return amount * 60 if unit.startswith(_HOUR_UNIT_PREFIXES) else amount

    for phrase, minutes in _FIXED_PHRASES.items():
        if phrase in normalized:
            return minutes

    return None
