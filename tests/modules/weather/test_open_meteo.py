from __future__ import annotations

import pytest

from modules.weather import open_meteo
from modules.weather.domain import WHEN_TODAY, WHEN_TOMORROW, resolve_day_offset


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


_GEOCODING_PAYLOAD = {"results": [{"name": "Киев", "latitude": 50.45, "longitude": 30.52}]}

# The real adapter always requests the full past_days=7/forecast_days=8
# window (see open_meteo._PAST_DAYS/_FORECAST_DAYS) regardless of which
# single day is actually asked for, so the fake payload must be the same
# 15-entry shape - index _PAST_DAYS (7) is "today", 8 is "tomorrow". Other
# indices are filler and never asserted on.
_TODAY_INDEX = resolve_day_offset(WHEN_TODAY) + 7
_TOMORROW_INDEX = resolve_day_offset(WHEN_TOMORROW) + 7
_FORECAST_PAYLOAD = {
    "daily": {
        "temperature_2m_max": [0.0] * 15,
        "temperature_2m_min": [0.0] * 15,
        "weathercode": [0] * 15,
        "windspeed_10m_max": [0.0] * 15,
    }
}
_FORECAST_PAYLOAD["daily"]["temperature_2m_max"][_TODAY_INDEX] = 20.0
_FORECAST_PAYLOAD["daily"]["temperature_2m_min"][_TODAY_INDEX] = 10.0
_FORECAST_PAYLOAD["daily"]["weathercode"][_TODAY_INDEX] = 0
_FORECAST_PAYLOAD["daily"]["windspeed_10m_max"][_TODAY_INDEX] = 15.0
_FORECAST_PAYLOAD["daily"]["temperature_2m_max"][_TOMORROW_INDEX] = 22.5
_FORECAST_PAYLOAD["daily"]["temperature_2m_min"][_TOMORROW_INDEX] = 12.0
_FORECAST_PAYLOAD["daily"]["weathercode"][_TOMORROW_INDEX] = 61
_FORECAST_PAYLOAD["daily"]["windspeed_10m_max"][_TOMORROW_INDEX] = 20.0


class _FakeAsyncClient:
    def __init__(self, geocoding_payload: dict, forecast_payload: dict) -> None:
        self._geocoding_response = _FakeResponse(geocoding_payload)
        self._forecast_response = _FakeResponse(forecast_payload)
        self.requested_urls: list[str] = []

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, params: dict) -> _FakeResponse:
        self.requested_urls.append(url)
        if "geocoding" in url:
            return self._geocoding_response
        return self._forecast_response


def _install_fake_client(monkeypatch, *, geocoding_payload=_GEOCODING_PAYLOAD, forecast_payload=_FORECAST_PAYLOAD):
    fake_client = _FakeAsyncClient(geocoding_payload, forecast_payload)
    monkeypatch.setattr(open_meteo.httpx, "AsyncClient", lambda timeout: fake_client)
    return fake_client


async def test_get_forecast_resolves_city_and_returns_todays_weather(monkeypatch) -> None:
    _install_fake_client(monkeypatch)

    forecast = await open_meteo.OpenMeteoAdapter().get_forecast("Киев", WHEN_TODAY)

    assert forecast.city == "Киев"
    assert forecast.when == resolve_day_offset(WHEN_TODAY)
    assert forecast.temperature_max_c == 20.0
    assert forecast.temperature_min_c == 10.0
    assert forecast.description == "ясно"
    assert forecast.wind_speed_max_kph == 15.0


async def test_get_forecast_picks_the_right_day_index_for_tomorrow(monkeypatch) -> None:
    _install_fake_client(monkeypatch)

    forecast = await open_meteo.OpenMeteoAdapter().get_forecast("Киев", WHEN_TOMORROW)

    assert forecast.temperature_max_c == 22.5
    assert forecast.description == "небольшой дождь"


async def test_get_forecast_raises_when_city_not_found(monkeypatch) -> None:
    _install_fake_client(monkeypatch, geocoding_payload={"results": []})

    with pytest.raises(open_meteo.WeatherLookupError):
        await open_meteo.OpenMeteoAdapter().get_forecast("Несуществующгород", WHEN_TODAY)


async def test_get_forecast_raises_on_unknown_when(monkeypatch) -> None:
    _install_fake_client(monkeypatch)

    with pytest.raises(open_meteo.WeatherLookupError):
        await open_meteo.OpenMeteoAdapter().get_forecast("Киев", "next_week")


async def test_get_forecast_queries_geocoding_then_forecast(monkeypatch) -> None:
    fake_client = _install_fake_client(monkeypatch)

    await open_meteo.OpenMeteoAdapter().get_forecast("Киев", WHEN_TODAY)

    assert "geocoding" in fake_client.requested_urls[0]
    assert "geocoding" not in fake_client.requested_urls[1]


# --- Oblique-case city name normalization (found live) ---------------------
# core/voice/intent.py's city regex extracts the city exactly as spoken -
# "в Киеве" -> "киеве", not the nominative "Киев" - and Open-Meteo's
# geocoding matches names fairly literally, so the raw oblique form either
# matched nothing ("одессе") or a coincidentally similar but wrong place
# ("киеве" -> "Киёвец", an actual small town, not Kyiv).


def test_city_geocoding_candidates_tries_masculine_then_feminine_then_raw() -> None:
    assert open_meteo._city_geocoding_candidates("киеве") == ["киев", "киева", "киеве"]


def test_city_geocoding_candidates_leaves_nominative_form_unchanged() -> None:
    assert open_meteo._city_geocoding_candidates("Киев") == ["Киев"]


class _FakeGeocodingByNameClient:
    """Unlike _FakeAsyncClient above, resolves geocoding per requested
    `name` - lets a test simulate the real-world case where only one of
    several candidate spellings actually returns a result."""

    def __init__(self, geocoding_by_name: dict[str, dict], forecast_payload: dict) -> None:
        self._geocoding_by_name = geocoding_by_name
        self._forecast_response = _FakeResponse(forecast_payload)
        self.requested_names: list[str] = []

    async def __aenter__(self) -> "_FakeGeocodingByNameClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, params: dict) -> _FakeResponse:
        if "geocoding" in url:
            self.requested_names.append(params["name"])
            return _FakeResponse(self._geocoding_by_name.get(params["name"], {"results": []}))
        return self._forecast_response


async def test_get_forecast_falls_back_through_candidates_until_one_matches(monkeypatch) -> None:
    # "киев" (the masculine-stem candidate) has no result, but "киева" (the
    # feminine-stem candidate, tried next) does - a real geocoding provider
    # would obviously never behave exactly like this for the same city, but
    # this isolates that the fallback loop itself tries every candidate in
    # order rather than giving up after the first miss.
    fake_client = _FakeGeocodingByNameClient(
        {"киева": {"results": [{"name": "Киев", "latitude": 50.45, "longitude": 30.52}]}}, _FORECAST_PAYLOAD
    )
    monkeypatch.setattr(open_meteo.httpx, "AsyncClient", lambda timeout: fake_client)

    forecast = await open_meteo.OpenMeteoAdapter().get_forecast("киеве", WHEN_TODAY)

    assert forecast.city == "Киев"
    assert fake_client.requested_names == ["киев", "киева"]
