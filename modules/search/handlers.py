from __future__ import annotations

from typing import Any

from core.dispatcher import CommandDispatcher
from modules.search import service_layer
from modules.search.google import GoogleSearchAdapter
from modules.search.ports import WebSearchPort

_engine: WebSearchPort = GoogleSearchAdapter()


async def _handle_web_search(params: dict[str, Any]) -> dict[str, Any]:
    return await service_layer.web_search(_engine, params.get("query"), int(params.get("num_results", 3)))


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "web_search",
        _handle_web_search,
        dangerous=False,
        description="Найти в Google (query, опционально num_results) и вернуть лучшие результаты.",
    )
