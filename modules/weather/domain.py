from __future__ import annotations

from dataclasses import dataclass

# Kept as named string constants (not just the day-offset integers below)
# since core/voice/intent.py's rule-based parser and the AI command
# classifier's prompt both already speak these words, not numbers, for the
# handful of common cases — "today"/"tomorrow" reads far more naturally in
# a command-description prompt than "0"/"1" would, and a weaker model is
# more likely to reach for a word it recognizes than to compute an offset
# itself for the common case (see resolve_day_offset below for what
# handles the arbitrary-day case: "через 5 дней"/"5 дней назад").
WHEN_TODAY = "today"
WHEN_TOMORROW = "tomorrow"
WHEN_DAY_AFTER_TOMORROW = "day_after_tomorrow"
WHEN_YESTERDAY = "yesterday"
WHEN_DAY_BEFORE_YESTERDAY = "day_before_yesterday"

_NAMED_DAY_OFFSETS: dict[str, int] = {
    WHEN_TODAY: 0,
    WHEN_TOMORROW: 1,
    WHEN_DAY_AFTER_TOMORROW: 2,
    WHEN_YESTERDAY: -1,
    WHEN_DAY_BEFORE_YESTERDAY: -2,
}

# Same window an ordinary weather app's history/forecast view offers - not
# arbitrary: Open-Meteo's forecast endpoint can go much further in both
# directions (past_days up to 92, forecast_days up to 16), but accuracy
# past about a week out is poor enough that showing it as a confident
# number would be misleading rather than just "less useful".
MIN_DAY_OFFSET = -7
MAX_DAY_OFFSET = 7


def resolve_day_offset(when: str | None) -> int:
    """Resolves a `when` value — one of the named keywords above, or a
    signed-integer string ("-3", "5") for an arbitrary day within the
    supported window — to a day offset from today (0), clamped to
    [MIN_DAY_OFFSET, MAX_DAY_OFFSET]. Raises WeatherLookupError-worthy
    ValueError for anything else (an unrecognized word like "next_week")
    rather than silently guessing "today" for it — the caller decides how
    to surface that.

    Clamping (not raising) for an in-range-but-out-of-bounds integer is
    deliberate: asking for 10 days ago and getting the 7-days-ago forecast
    back, clearly labeled as such (see day_offset_label), is a reasonable
    approximation; a bare error for a perfectly well-formed request is not
    friendlier just because the number was a bit too big."""
    if not when:
        return 0
    if when in _NAMED_DAY_OFFSETS:
        return _NAMED_DAY_OFFSETS[when]
    offset = int(when)  # raises ValueError for anything not a plain signed integer
    return max(MIN_DAY_OFFSET, min(MAX_DAY_OFFSET, offset))


def _days_word(n: int) -> str:
    """Russian pluralization of "день" for a bare count: 1 день, 2-4 дня,
    5-20 дней, then the pattern repeats (21 день, 22 дня, 25 дней, ...)."""
    if 11 <= n % 100 <= 14:
        return "дней"
    last_digit = n % 10
    if last_digit == 1:
        return "день"
    if 2 <= last_digit <= 4:
        return "дня"
    return "дней"


def day_offset_label(offset: int) -> str:
    """Human phrasing for a resolved day offset — the same five named cases
    read naturally as fixed words; anything further out (still within
    [MIN_DAY_OFFSET, MAX_DAY_OFFSET]) is phrased as "через N дней"/"N дней
    назад" rather than needing a name for every possible day."""
    if offset == 0:
        return "сегодня"
    if offset == 1:
        return "завтра"
    if offset == 2:
        return "послезавтра"
    if offset == -1:
        return "вчера"
    if offset == -2:
        return "позавчера"
    if offset > 0:
        return f"через {offset} {_days_word(offset)}"
    return f"{abs(offset)} {_days_word(abs(offset))} назад"


# WMO weather codes (used by Open-Meteo's `weathercode`/`weather_code`
# field) - not exhaustive, but covers every code Open-Meteo's docs actually
# document; an unrecognized code still gets a reasonable fallback rather
# than raising.
_WEATHER_CODE_RU: dict[int, str] = {
    0: "ясно",
    1: "малооблачно",
    2: "переменная облачность",
    3: "пасмурно",
    45: "туман",
    48: "туман с изморозью",
    51: "лёгкая морось",
    53: "морось",
    55: "сильная морось",
    56: "лёгкая ледяная морось",
    57: "сильная ледяная морось",
    61: "небольшой дождь",
    63: "дождь",
    65: "сильный дождь",
    66: "лёгкий ледяной дождь",
    67: "сильный ледяной дождь",
    71: "небольшой снег",
    73: "снег",
    75: "сильный снегопад",
    77: "снежные зёрна",
    80: "небольшой ливень",
    81: "ливень",
    82: "сильный ливень",
    85: "небольшой снегопад",
    86: "сильный снегопад",
    95: "гроза",
    96: "гроза с небольшим градом",
    99: "гроза с сильным градом",
}


def describe_weather_code(code: int) -> str:
    return _WEATHER_CODE_RU.get(code, "неопределённая погода")


@dataclass(frozen=True)
class WeatherForecast:
    city: str
    # A resolved day offset from today (see resolve_day_offset above), not
    # the raw "when" string the caller asked with — WeatherPort.get_forecast
    # implementations resolve it before constructing this.
    when: int
    temperature_max_c: float
    temperature_min_c: float
    description: str
    wind_speed_max_kph: float | None = None

    def to_message(self) -> str:
        # Spelled out ("градусов", "километров в час"), not "°C"/"км/ч" —
        # found live: Silero's built-in text normalizer isn't tested or
        # adapted for the "°" symbol or slash-abbreviated units at all, and
        # a number glued directly against "°C" with no space garbled the
        # speech audibly right at the temperature (letters dropped/
        # mangled), even though the same normalizer handles a plain number
        # followed by an ordinary word just fine elsewhere in this same
        # message.
        when_label = day_offset_label(self.when)
        message = (
            f"Погода в городе {self.city} {when_label}: {self.description}, "
            f"температура от {self.temperature_min_c:.0f} до {self.temperature_max_c:.0f} градусов."
        )
        if self.wind_speed_max_kph is not None:
            message += f" Ветер до {self.wind_speed_max_kph:.0f} километров в час."
        return message
