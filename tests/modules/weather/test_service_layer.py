from __future__ import annotations

import pytest

from modules.weather import service_layer
from modules.weather.domain import WHEN_TODAY, WHEN_TOMORROW, WeatherForecast, resolve_day_offset


class _FakeEngine:
    def __init__(self, forecast: WeatherForecast) -> None:
        self._forecast = forecast
        self.last_call: tuple[str, str] | None = None

    async def get_forecast(self, city: str, when: str) -> WeatherForecast:
        self.last_call = (city, when)
        return self._forecast


def _forecast(**overrides) -> WeatherForecast:
    # WeatherForecast.when stores a resolved day *offset* (int) - distinct
    # from the raw WHEN_TODAY/WHEN_TOMORROW keyword strings _FakeEngine's
    # get_forecast is called with below, which are unaffected by that.
    defaults = dict(
        city="Киев", when=resolve_day_offset(WHEN_TODAY), temperature_max_c=20.0, temperature_min_c=10.0,
        description="ясно", wind_speed_max_kph=15.0,
    )
    defaults.update(overrides)
    return WeatherForecast(**defaults)


async def test_get_weather_returns_the_forecast_and_a_spoken_message() -> None:
    engine = _FakeEngine(_forecast())

    result = await service_layer.get_weather(engine, "Киев", None)

    assert engine.last_call == ("Киев", WHEN_TODAY)  # defaults to today when `when` is omitted
    assert result["city"] == "Киев"
    assert "Киев" in result["message"]


async def test_get_weather_passes_through_the_requested_when() -> None:
    engine = _FakeEngine(_forecast(when=resolve_day_offset(WHEN_TOMORROW)))

    await service_layer.get_weather(engine, "Киев", WHEN_TOMORROW)

    assert engine.last_call == ("Киев", WHEN_TOMORROW)


async def test_get_weather_raises_when_no_city_given() -> None:
    engine = _FakeEngine(_forecast())

    with pytest.raises(ValueError):
        await service_layer.get_weather(engine, None, None)

    with pytest.raises(ValueError):
        await service_layer.get_weather(engine, "", None)


async def test_get_weather_falls_back_to_the_profile_city_when_none_spoken() -> None:
    engine = _FakeEngine(_forecast(city="Одесса"))

    await service_layer.get_weather(engine, None, None, profile_city_lookup=lambda: "Одесса")

    assert engine.last_call == ("Одесса", WHEN_TODAY)


async def test_get_weather_prefers_the_spoken_city_over_the_profile_one() -> None:
    engine = _FakeEngine(_forecast())

    await service_layer.get_weather(engine, "Киев", None, profile_city_lookup=lambda: "Одесса")

    assert engine.last_call == ("Киев", WHEN_TODAY)


async def test_get_weather_falls_back_to_geolocation_when_profile_has_no_city() -> None:
    engine = _FakeEngine(_forecast(city="Львов"))

    async def geolocate() -> str:
        return "Львов"

    await service_layer.get_weather(
        engine, None, None, profile_city_lookup=lambda: None, geolocate=geolocate
    )

    assert engine.last_call == ("Львов", WHEN_TODAY)


async def test_get_weather_raises_when_every_fallback_comes_up_empty() -> None:
    engine = _FakeEngine(_forecast())

    async def geolocate() -> None:
        return None

    with pytest.raises(ValueError):
        await service_layer.get_weather(
            engine, None, None, profile_city_lookup=lambda: None, geolocate=geolocate
        )
