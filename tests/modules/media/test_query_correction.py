from __future__ import annotations

import asyncio

import pytest

import core.ai_adapter_chain as ai_adapter_chain
from modules.media.query_correction import correct_query


class _FakeAdapter:
    def __init__(self, name: str, reply: str) -> None:
        self.name = name
        self._reply = reply

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
        return self._reply


class _FailingAdapter:
    name = "failing"

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
        raise RuntimeError("boom")


def test_correct_query_returns_ai_corrected_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: _FakeAdapter("local", "Dead Cells"))
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: _FailingAdapter())

    result = asyncio.run(correct_query("дед селс"))

    assert result == "Dead Cells"


def test_correct_query_strips_surrounding_quotes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: _FakeAdapter("local", '"Rick and Morty"'))
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: _FailingAdapter())

    result = asyncio.run(correct_query("рик энд морти"))

    assert result == "Rick and Morty"


def test_correct_query_falls_through_to_cloud_when_local_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: _FailingAdapter())
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: _FakeAdapter("ai_bridge", "Stranger Things"))

    result = asyncio.run(correct_query("стрейнджер тингс"))

    assert result == "Stranger Things"


def test_correct_query_falls_back_to_original_text_when_every_adapter_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    # Unlike modules.media.recommender.recommend (which has nothing sane to
    # fall back to and returns None), an uncorrected search query is still
    # strictly better than giving up on the search entirely.
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: None)
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: _FailingAdapter())

    result = asyncio.run(correct_query("дед селс"))

    assert result == "дед селс"


def test_correct_query_falls_back_to_original_text_on_empty_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: _FakeAdapter("local", "   "))
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: _FailingAdapter())

    result = asyncio.run(correct_query("дед селс"))

    assert result == "дед селс"


def test_correct_query_returns_empty_string_unchanged_without_calling_any_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: calls.append("local") or None)
    monkeypatch.setattr(
        ai_adapter_chain, "get_provider_manager", lambda: calls.append("cloud") or _FailingAdapter()
    )

    result = asyncio.run(correct_query("   "))

    assert result == ""
    assert calls == []
