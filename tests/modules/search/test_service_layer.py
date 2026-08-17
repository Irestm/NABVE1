from __future__ import annotations

import pytest

from modules.search import service_layer


class _FakeSearchEngine:
    def __init__(self, results: list[dict[str, str]]) -> None:
        self._results = results
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, num_results: int) -> list[dict[str, str]]:
        self.calls.append((query, num_results))
        return self._results


async def test_web_search_raises_when_query_missing() -> None:
    with pytest.raises(ValueError, match="query"):
        await service_layer.web_search(_FakeSearchEngine([]), None, 3)


async def test_web_search_returns_results_and_summary() -> None:
    engine = _FakeSearchEngine([{"title": "Python", "url": "https://python.org", "snippet": "Official site"}])

    result = await service_layer.web_search(engine, "python", 3)

    assert result["results"] == engine._results
    assert result["summary"] == "1. Python. Official site"
    assert result["message"] == result["summary"]
    assert engine.calls == [("python", 3)]


async def test_web_search_summary_for_no_results() -> None:
    engine = _FakeSearchEngine([])

    result = await service_layer.web_search(engine, "obscure query", 3)

    assert result["summary"] == "No results found."
