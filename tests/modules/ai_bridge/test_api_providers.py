from __future__ import annotations

import dataclasses

import httpx
import pytest

from modules.ai_bridge import api_providers
from modules.ai_bridge.quota_tracker import QuotaTracker


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    """Installed via monkeypatch.setattr(httpx, "AsyncClient", ...) — same
    pattern as tests/core/test_telegram_notifier.py's _FakeAsyncClient."""

    def __init__(self, **kwargs: object) -> None:
        self.requests: list[dict] = []

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, headers: dict, json: dict) -> _FakeResponse:
        self.requests.append({"url": url, "headers": headers, "json": json})
        return _FakeResponse({"choices": [{"message": {"content": "hi there"}}]})


@pytest.fixture(autouse=True)
def _no_system_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_providers, "apply_system_prompt", lambda text: text)


@pytest.mark.asyncio
async def test_send_prompt_returns_the_models_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    adapter = api_providers.GroqApiAdapter("fake-key", QuotaTracker())

    reply = await adapter.send_prompt("hello")

    assert reply == "hi there"


@pytest.mark.asyncio
async def test_send_prompt_sends_the_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class _CapturingClient(_FakeAsyncClient):
        async def post(self, url: str, headers: dict, json: dict) -> _FakeResponse:
            captured["headers"] = headers
            captured["json"] = json
            return await super().post(url, headers, json)

    monkeypatch.setattr(httpx, "AsyncClient", _CapturingClient)
    adapter = api_providers.GroqApiAdapter("secret-key", QuotaTracker())

    await adapter.send_prompt("hello")

    assert captured["headers"]["Authorization"] == "Bearer secret-key"
    assert captured["json"]["messages"] == [{"role": "user", "content": "hello"}]


@pytest.mark.asyncio
async def test_send_prompt_records_usage_in_the_quota_tracker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    quota = QuotaTracker()
    adapter = api_providers.GroqApiAdapter("fake-key", quota)

    for _ in range(20):
        await adapter.send_prompt("hello")

    assert quota.is_near_limit("groq_api") is True


def test_get_adapter_returns_none_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_providers, "settings", dataclasses.replace(api_providers.settings, groq_api_key=None))
    monkeypatch.setattr(api_providers, "_adapter", None)
    monkeypatch.setattr(api_providers, "_adapter_initialized", False)

    assert api_providers.get_adapter() is None


def test_get_adapter_returns_cached_instance_when_key_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        api_providers, "settings", dataclasses.replace(api_providers.settings, groq_api_key="fake-key")
    )
    monkeypatch.setattr(api_providers, "_adapter", None)
    monkeypatch.setattr(api_providers, "_adapter_initialized", False)

    first = api_providers.get_adapter()
    second = api_providers.get_adapter()

    assert first is not None
    assert first is second


# --- Gemini ------------------------------------------------------------------


class _FakeGeminiClient(_FakeAsyncClient):
    async def post(self, url: str, params: dict, json: dict) -> _FakeResponse:
        self.requests.append({"url": url, "params": params, "json": json})
        return _FakeResponse({"candidates": [{"content": {"parts": [{"text": "hi from gemini"}]}}]})


@pytest.mark.asyncio
async def test_gemini_send_prompt_returns_the_models_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", _FakeGeminiClient)
    adapter = api_providers.GeminiApiAdapter("fake-key", QuotaTracker())

    reply = await adapter.send_prompt("hello")

    assert reply == "hi from gemini"


@pytest.mark.asyncio
async def test_gemini_send_prompt_sends_the_key_as_a_query_param(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class _CapturingClient(_FakeGeminiClient):
        async def post(self, url: str, params: dict, json: dict) -> _FakeResponse:
            captured["params"] = params
            return await super().post(url, params, json)

    monkeypatch.setattr(httpx, "AsyncClient", _CapturingClient)
    adapter = api_providers.GeminiApiAdapter("secret-key", QuotaTracker())

    await adapter.send_prompt("hello")

    assert captured["params"] == {"key": "secret-key"}


@pytest.mark.asyncio
async def test_gemini_send_prompt_records_both_minute_and_daily_usage(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from modules.ai_bridge.state_store import StateStore

    monkeypatch.setattr(httpx, "AsyncClient", _FakeGeminiClient)
    quota = QuotaTracker(daily_store=StateStore(db_path=tmp_path / "daily.db"))
    adapter = api_providers.GeminiApiAdapter("fake-key", quota)

    await adapter.send_prompt("hello")

    assert quota.is_near_limit("gemini_api", limit=1) is True
    assert quota.daily_count("gemini_api") == 1


def test_get_gemini_adapter_returns_none_without_a_stored_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_providers, "get_secret", lambda name: None)
    monkeypatch.setattr(api_providers, "_gemini_adapter", None)
    monkeypatch.setattr(api_providers, "_gemini_adapter_key", None)

    assert api_providers.get_gemini_adapter() is None


def test_get_gemini_adapter_rebuilds_when_the_stored_key_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    stored_key = {"value": "key-one"}
    monkeypatch.setattr(api_providers, "get_secret", lambda name: stored_key["value"])
    monkeypatch.setattr(api_providers, "_gemini_adapter", None)
    monkeypatch.setattr(api_providers, "_gemini_adapter_key", None)

    first = api_providers.get_gemini_adapter()
    same = api_providers.get_gemini_adapter()
    stored_key["value"] = "key-two"
    changed = api_providers.get_gemini_adapter()

    assert first is same
    assert changed is not first
    assert changed is not None and changed._api_key == "key-two"


# --- Claude --------------------------------------------------------------


class _FakeClaudeClient(_FakeAsyncClient):
    async def post(self, url: str, headers: dict, json: dict) -> _FakeResponse:
        self.requests.append({"url": url, "headers": headers, "json": json})
        return _FakeResponse({"content": [{"text": "hi from claude"}]})


@pytest.mark.asyncio
async def test_claude_send_prompt_returns_the_models_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClaudeClient)
    adapter = api_providers.ClaudeApiAdapter("fake-key")

    reply = await adapter.send_prompt("hello")

    assert reply == "hi from claude"


@pytest.mark.asyncio
async def test_claude_send_prompt_sends_the_api_key_header(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class _CapturingClient(_FakeClaudeClient):
        async def post(self, url: str, headers: dict, json: dict) -> _FakeResponse:
            captured["headers"] = headers
            return await super().post(url, headers, json)

    monkeypatch.setattr(httpx, "AsyncClient", _CapturingClient)
    adapter = api_providers.ClaudeApiAdapter("secret-key")

    await adapter.send_prompt("hello")

    assert captured["headers"]["x-api-key"] == "secret-key"


def test_get_claude_adapter_returns_none_without_a_stored_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_providers, "get_secret", lambda name: None)
    monkeypatch.setattr(api_providers, "_claude_adapter", None)
    monkeypatch.setattr(api_providers, "_claude_adapter_key", None)

    assert api_providers.get_claude_adapter() is None


def test_get_claude_adapter_returns_cached_instance_for_the_same_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_providers, "get_secret", lambda name: "fake-key")
    monkeypatch.setattr(api_providers, "_claude_adapter", None)
    monkeypatch.setattr(api_providers, "_claude_adapter_key", None)

    first = api_providers.get_claude_adapter()
    second = api_providers.get_claude_adapter()

    assert first is not None
    assert first is second
