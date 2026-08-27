from __future__ import annotations

import httpx

from modules.weather.domain import (
    MAX_DAY_OFFSET,
    MIN_DAY_OFFSET,
    WeatherForecast,
    describe_weather_code,
    resolve_day_offset,
)

_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_REQUEST_TIMEOUT_SECONDS = 10.0

# past_days covers MIN_DAY_OFFSET days of *actual observed* weather (Open-
# Meteo backs this with ERA5 reanalysis data on the same endpoint, not a
# separate historical API/call) before today; forecast_days covers today
# itself plus MAX_DAY_OFFSET days ahead. Always requesting the full window
# regardless of the single day actually asked for keeps this to one
# request shape - Open-Meteo is free/unauthenticated, so the extra days
# in the response cost nothing extra to ask for.
_PAST_DAYS = -MIN_DAY_OFFSET
_FORECAST_DAYS = MAX_DAY_OFFSET + 1


class WeatherLookupError(RuntimeError):
    pass


def _city_geocoding_candidates(city: str) -> list[str]:
    """Best-guess nominative-case spellings to try before the raw form as
    spoken - core/voice/intent.py's city regex extracts the city exactly as
    said, which in Russian/Ukrainian is almost always some oblique case
    ("в Киеве" -> "киеве", not "Киев") since "в"/"на"/"у" all govern a case
    other than nominative, but Open-Meteo's geocoding matches names fairly
    literally. Found live: the raw oblique form either matched nothing at
    all ("одессе") or, worse, silently matched an unrelated place with a
    similar spelling ("киеве" -> "Киёвец", an actual small town, not Kyiv).
    Candidates are tried in order and the first with any result wins, so a
    correct guess here is never shadowed by that kind of coincidental wrong
    match on the raw form.

    Covers the two dominant Slavic prepositional-case patterns: masculine/
    neuter nouns take -е/-і (Киев -> Киеве, Львів -> Львові) and feminine
    -а/-я nouns replace their ending with -е/-і (Одесса -> Одессе, Прага ->
    Праге). Not a real morphological analyzer (no new dependency for this),
    so it won't get every irregular city name, but it covers ordinary ones,
    which is what's actually asked in practice; the raw form is always
    still tried last as a fallback."""
    candidates = [city]
    if len(city) > 2 and city[-1] in ("е", "і"):
        stem = city[:-1]
        candidates[:0] = [stem, f"{stem}а"]
    return candidates


class OpenMeteoAdapter:
    """No API key required - Open-Meteo's geocoding + forecast APIs are
    free for non-commercial use with no registration. Two calls per
    request (resolve the city name to coordinates, then fetch the
    forecast for those coordinates) since Open-Meteo's forecast endpoint
    only accepts lat/lon, not a place name."""

    async def get_forecast(self, city: str, when: str) -> WeatherForecast:
        try:
            day_offset = resolve_day_offset(when)
        except ValueError as exc:
            raise WeatherLookupError(f"Неизвестный период прогноза: {when!r}.") from exc
        # _PAST_DAYS is index 0 in the arrays below (today - _PAST_DAYS),
        # so a resolved offset of 0 (today) lands at index _PAST_DAYS.
        day_index = _PAST_DAYS + day_offset

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            place: dict | None = None
            for candidate in _city_geocoding_candidates(city):
                geocoding_response = await client.get(
                    _GEOCODING_URL, params={"name": candidate, "count": 1, "language": "ru", "format": "json"}
                )
                geocoding_response.raise_for_status()
                results = geocoding_response.json().get("results")
                if results:
                    place = results[0]
                    break
            if place is None:
                raise WeatherLookupError(f"Не удалось найти город «{city}».")
            resolved_name = place.get("name", city)
            latitude = place["latitude"]
            longitude = place["longitude"]

            forecast_response = await client.get(
                _FORECAST_URL,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "daily": "temperature_2m_max,temperature_2m_min,weathercode,windspeed_10m_max",
                    "timezone": "auto",
                    "past_days": _PAST_DAYS,
                    "forecast_days": _FORECAST_DAYS,
                },
            )
            forecast_response.raise_for_status()
            daily = forecast_response.json().get("daily", {})

        try:
            temperature_max = daily["temperature_2m_max"][day_index]
            temperature_min = daily["temperature_2m_min"][day_index]
            weather_code = daily["weathercode"][day_index]
        except (KeyError, IndexError) as exc:
            raise WeatherLookupError(f"Прогноз на этот период для «{city}» недоступен.") from exc
        wind_speed_values = daily.get("windspeed_10m_max")
        wind_speed_max = wind_speed_values[day_index] if wind_speed_values and len(wind_speed_values) > day_index else None

        return WeatherForecast(
            city=resolved_name,
            when=day_offset,
            temperature_max_c=temperature_max,
            temperature_min_c=temperature_min,
            description=describe_weather_code(weather_code),
            wind_speed_max_kph=wind_speed_max,
        )
