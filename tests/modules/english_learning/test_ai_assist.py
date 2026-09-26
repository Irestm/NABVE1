from __future__ import annotations

import asyncio
from typing import Any

from modules.ai_bridge.providers.base import AIResult
from modules.english_learning import ai_assist
from modules.english_learning.link_parser import LinkGuess


class _Router:
    def __init__(self, parsed: Any) -> None:
        self.parsed = parsed
        self.schemas: list[Any] = []

    async def complete(self, messages: Any, *, json_schema: Any = None, max_tokens: int = 0, kind: str = "default") -> AIResult:
        self.schemas.append(json_schema)
        return AIResult(text="{}", provider_name="fake", parsed_json=self.parsed)


def test_resolve_link_fills_only_missing_fields() -> None:
    router = _Router({"series_title": "Dark", "season": 2, "episode": 4, "alternatives": ["Dark (2017)", ""]})
    guess = LinkGuess("https://x", None, 1, None, page_title="Dark stream")

    resolved, alternatives = asyncio.run(ai_assist.resolve_link(guess, router))  # type: ignore[arg-type]

    assert (resolved.series_title, resolved.season, resolved.episode) == ("Dark", 1, 4)
    assert alternatives == ["Dark (2017)"]
    assert router.schemas == [ai_assist.LINK_SCHEMA]


def test_resolve_link_tolerates_garbage() -> None:
    guess = LinkGuess("https://x", None, None, None)

    resolved, alternatives = asyncio.run(ai_assist.resolve_link(guess, _Router("nope")))  # type: ignore[arg-type]

    assert resolved.series_title is None and alternatives == []


def test_guess_dialogue_builds_ordered_cues() -> None:
    router = _Router({"lines": [{"text": "We need to talk.", "minute": 2}, {"text": " ", "minute": 3}, {"text": "Fine.", "minute": 1}, "bad"]})

    cues = asyncio.run(ai_assist.guess_dialogue("Dark", 1, 1, "Secrets", router))  # type: ignore[arg-type]

    assert [cue.text for cue in cues] == ["We need to talk.", "Fine."]
    assert cues[0].start_ms == 120_000
