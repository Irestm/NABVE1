from __future__ import annotations

from modules.weather.domain import (
    WHEN_TODAY,
    WHEN_TOMORROW,
    WeatherForecast,
    describe_weather_code,
    resolve_day_offset,
)

# WeatherForecast.when stores a resolved day *offset* (int), not the raw
# "when" keyword string a caller asks with - see resolve_day_offset.
_TODAY = resolve_day_offset(WHEN_TODAY)
_TOMORROW = resolve_day_offset(WHEN_TOMORROW)


def test_describe_weather_code_maps_known_codes() -> None:
    assert describe_weather_code(0) == "ясно"
    assert describe_weather_code(61) == "небольшой дождь"


def test_describe_weather_code_falls_back_for_unknown_codes() -> None:
    assert describe_weather_code(12345) == "неопределённая погода"


def test_to_message_includes_city_temperature_range_and_wind() -> None:
    forecast = WeatherForecast(
        city="Киев", when=_TOMORROW, temperature_max_c=22.5, temperature_min_c=12.0,
        description="небольшой дождь", wind_speed_max_kph=20.0,
    )

    message = forecast.to_message()

    assert "Киев" in message
    assert "завтра" in message
    assert "небольшой дождь" in message
    assert "12" in message and "22" in message
    assert "20" in message


def test_to_message_omits_wind_when_not_available() -> None:
    forecast = WeatherForecast(
        city="Киев", when=_TODAY, temperature_max_c=20.0, temperature_min_c=10.0,
        description="ясно", wind_speed_max_kph=None,
    )

    assert "Ветер" not in forecast.to_message()


def test_to_message_spells_out_units_instead_of_symbols_for_tts() -> None:
    # Regression, found live: "22°C"/"20 км/ч" (number glued directly
    # against a "°" symbol or a slash-abbreviated unit) garbled Silero's
    # speech audibly right at the temperature - spelling units out as plain
    # words avoids relying on its text normalizer handling either at all.
    forecast = WeatherForecast(
        city="Киев", when=_TOMORROW, temperature_max_c=22.5, temperature_min_c=12.0,
        description="небольшой дождь", wind_speed_max_kph=20.0,
    )

    message = forecast.to_message()

    assert "°" not in message
    assert "км/ч" not in message
    assert "градусов" in message
    assert "километров в час" in message
