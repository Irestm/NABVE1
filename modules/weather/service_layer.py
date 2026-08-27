from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from modules.weather.domain import WHEN_TODAY
from modules.weather.ports import WeatherPort


async def get_weather(
    engine: WeatherPort,
    city: str | None,
    when: str | None,
    *,
    profile_city_lookup: Callable[[], str | None] | None = None,
    geolocate: Callable[[], Awaitable[str | None]] | None = None,
) -> dict[str, Any]:
    """Resolves which city to check in order: the city spoken in this exact
    utterance, then (if the caller supplied one) `profile_city_lookup` — a
    home city the user explicitly set once (see
    modules.user_profile.domain.CITY_KEY) — then `geolocate` — a best-effort
    IP-based guess (see modules/weather/geolocation.py), the fallback the
    user asked for by name. Both fallbacks are optional/injectable so tests
    don't need a real profile DB or network access to exercise the "city
    was spoken" and "no city, no fallbacks configured" paths; handlers.py
    wires the real ones for actual voice/API calls."""
    resolved_city = city
    if not resolved_city and profile_city_lookup is not None:
        resolved_city = profile_city_lookup()
    if not resolved_city and geolocate is not None:
        resolved_city = await geolocate()
    if not resolved_city:
        raise ValueError("Не указан город. Скажите, например: «какая погода в Киеве».")

    forecast = await engine.get_forecast(resolved_city, when or WHEN_TODAY)
    return {
        "city": forecast.city,
        "when": forecast.when,
        "temperature_max_c": forecast.temperature_max_c,
        "temperature_min_c": forecast.temperature_min_c,
        "description": forecast.description,
        "wind_speed_max_kph": forecast.wind_speed_max_kph,
        "message": forecast.to_message(),
    }
