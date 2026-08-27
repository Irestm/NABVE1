from __future__ import annotations

from typing import Any

from core.dispatcher import CommandDispatcher
from modules.user_profile import service_layer as profile_service_layer
from modules.user_profile.domain import CITY_KEY
from modules.user_profile.uow import ProfileUnitOfWork
from modules.weather import service_layer
from modules.weather.geolocation import detect_city_from_ip
from modules.weather.open_meteo import OpenMeteoAdapter
from modules.weather.ports import WeatherPort

_engine: WeatherPort = OpenMeteoAdapter()


def _lookup_profile_city() -> str | None:
    return profile_service_layer.get_fact(ProfileUnitOfWork(), CITY_KEY)


async def _handle_weather_get(params: dict[str, Any]) -> dict[str, Any]:
    return await service_layer.get_weather(
        _engine,
        params.get("city"),
        params.get("when"),
        profile_city_lookup=_lookup_profile_city,
        geolocate=detect_city_from_ip,
    )


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "weather_get",
        _handle_weather_get,
        dangerous=False,
        description=(
            "Узнать прогноз погоды (city — необязательный город, если не указан — "
            "берётся из профиля или определяется по IP; when — "
            "'today'/'tomorrow'/'day_after_tomorrow'/'yesterday'/'day_before_yesterday', "
            "или строка с числом дней от сегодня со знаком (например '-5' — 5 дней назад, "
            "'3' — через 3 дня), от -7 до 7, по умолчанию 'today')."
        ),
    )
