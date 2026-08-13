from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class WebSearchPort(Protocol):
    async def search(self, query: str, num_results: int = 3) -> list[dict[str, str]]: ...
