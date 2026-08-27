from __future__ import annotations

from typing import Protocol, runtime_checkable

from modules.weather.domain import WeatherForecast


@runtime_checkable
class WeatherPort(Protocol):
    async def get_forecast(self, city: str, when: str) -> WeatherForecast: ...
