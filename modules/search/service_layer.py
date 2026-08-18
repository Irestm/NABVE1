from __future__ import annotations

from typing import Any

from modules.search.google import build_summary
from modules.search.ports import WebSearchPort


async def web_search(engine: WebSearchPort, query: str | None, num_results: int) -> dict[str, Any]:
    if not query:
        raise ValueError("Не указан запрос для поиска.")
    results = await engine.search(query, num_results=num_results)
    summary = build_summary(results)
    return {"results": results, "summary": summary, "message": summary}
