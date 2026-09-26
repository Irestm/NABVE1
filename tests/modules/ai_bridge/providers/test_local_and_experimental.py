from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from modules.ai_bridge.providers import ollama as ollama_module
from modules.ai_bridge.providers.base import ProviderBadResponse, ProviderRateLimited, ProviderUnavailable
from modules.ai_bridge.providers.experimental import browser_chain as browser_chain_module
from modules.ai_bridge.providers.experimental.browser_chain import BrowserChainProvider
from modules.ai_bridge.providers.experimental.provider_manager import AllProvidersExhaustedError
from modules.ai_bridge.providers.ollama import OllamaProvider

_MESSAGES: list[Any] = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "вопрос"}]


class _FakeLocalAdapter:
    tier = "small"

    def __init__(self, reply: str = "ответ", error: Exception | None = None) -> None:
        self._reply = reply
        self._error = error
        self.received: dict[str, Any] = {}

    async def chat(self, messages: list[dict[str, str]], *, json_schema: Any = None, max_tokens: int = 512) -> str:
        self.received = {"messages": messages, "json_schema": json_schema, "max_tokens": max_tokens}
        if self._error is not None:
            raise self._error
        return self._reply

    async def chat_stream(self, messages: list[dict[str, str]], *, max_tokens: int = 512) -> AsyncIterator[str]:
        for piece in ("о", "к"):
            yield piece


def _use_local(monkeypatch: pytest.MonkeyPatch, adapter: _FakeLocalAdapter | None) -> None:
    monkeypatch.setattr(ollama_module.local_ai, "get_adapter", lambda: adapter)
    monkeypatch.setattr(ollama_module.local_ai, "unavailable_reason", lambda: "no GPU")


def test_ollama_passes_messages_schema_and_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _FakeLocalAdapter('{"a": 1}')
    _use_local(monkeypatch, adapter)

    result = asyncio.run(OllamaProvider().complete(_MESSAGES, json_schema={"type": "object"}, max_tokens=77))

    assert result.parsed_json == {"a": 1}
    assert adapter.received["messages"] == _MESSAGES
    assert adapter.received["json_schema"] == {"type": "object"}
    assert adapter.received["max_tokens"] == 77


def test_ollama_without_local_model_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_local(monkeypatch, None)
    provider = OllamaProvider()

    assert provider.is_ready() is False
    with pytest.raises(ProviderUnavailable, match="no GPU"):
        asyncio.run(provider.complete(_MESSAGES, max_tokens=10))


def test_ollama_http_failure_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_local(monkeypatch, _FakeLocalAdapter(error=httpx.ConnectError("refused")))

    with pytest.raises(ProviderUnavailable):
        asyncio.run(OllamaProvider().complete(_MESSAGES, max_tokens=10))


def test_ollama_empty_reply_is_bad_response(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_local(monkeypatch, _FakeLocalAdapter(""))

    with pytest.raises(ProviderBadResponse):
        asyncio.run(OllamaProvider().complete(_MESSAGES, max_tokens=10))


def test_ollama_streams_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_local(monkeypatch, _FakeLocalAdapter())

    async def _collect() -> list[str]:
        return [piece async for piece in OllamaProvider().stream(_MESSAGES, max_tokens=10)]

    assert asyncio.run(_collect()) == ["о", "к"]


class _FakeManager:
    def __init__(self, reply: str = "из браузера", error: Exception | None = None) -> None:
        self._reply = reply
        self._error = error
        self.prompts: list[str] = []

    async def send_raw(self, prompt: str, *, fast_mode: bool = True) -> str:
        self.prompts.append(prompt)
        if self._error is not None:
            raise self._error
        return self._reply

    def status(self) -> dict[str, Any]:
        return {"active_provider": "gemini"}


def test_browser_chain_is_experimental_and_flattens_messages_without_double_persona(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _FakeManager()
    monkeypatch.setattr(browser_chain_module, "get_provider_manager", lambda: manager)

    result = asyncio.run(BrowserChainProvider().complete(_MESSAGES, max_tokens=10))

    assert BrowserChainProvider.experimental is True
    assert result.text == "из браузера"
    assert manager.prompts == ["SYS\n\nвопрос"]


def test_browser_chain_maps_exhausted_limits_to_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        browser_chain_module, "get_provider_manager", lambda: _FakeManager(error=AllProvidersExhaustedError("all"))
    )

    with pytest.raises(ProviderRateLimited):
        asyncio.run(BrowserChainProvider().complete(_MESSAGES, max_tokens=10))


def test_browser_chain_health_carries_the_risk_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser_chain_module, "get_provider_manager", lambda: _FakeManager())

    health = asyncio.run(BrowserChainProvider().health())

    assert health.experimental is True
    assert "свой риск" in health.extra["warning"]
