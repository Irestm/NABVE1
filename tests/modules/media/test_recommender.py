from __future__ import annotations

import asyncio

import pytest

import core.ai_adapter_chain as ai_adapter_chain
from modules.media.recommender import recommend


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


def test_recommend_returns_query_from_local_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: _FakeAdapter("local", "Queen - Bohemian Rhapsody"))
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: _FailingAdapter())

    result = asyncio.run(recommend("music", "грустное"))

    assert result == "Queen - Bohemian Rhapsody"


def test_recommend_strips_surrounding_quotes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: _FakeAdapter("local", '"lofi hip hop mix"'))
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: _FailingAdapter())

    result = asyncio.run(recommend("music", "спокойное"))

    assert result == "lofi hip hop mix"


def test_recommend_falls_through_to_cloud_when_local_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: _FailingAdapter())
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: _FakeAdapter("ai_bridge", "relaxing piano music"))

    result = asyncio.run(recommend("video", "уставший"))

    assert result == "relaxing piano music"


def test_recommend_returns_none_when_every_adapter_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: None)
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: _FailingAdapter())

    assert asyncio.run(recommend("music", "радостное")) is None


def test_recommend_treats_empty_reply_as_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: _FakeAdapter("local", "   "))
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: _FakeAdapter("ai_bridge", "jazz classics"))

    result = asyncio.run(recommend("music", "спокойное"))

    assert result == "jazz classics"
