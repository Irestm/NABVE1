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
