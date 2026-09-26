from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

import pytest

from modules.ai_bridge.providers import router as router_module
from modules.ai_bridge.providers.base import (
    AIResult,
    AllProvidersFailed,
    ChatMessage,
    ProviderAuthError,
    ProviderBadResponse,
    ProviderHealth,
    ProviderRateLimited,
    ProviderUnavailable,
)
from modules.ai_bridge.providers.config import ProvidersConfig
from modules.ai_bridge.providers.router import PromptPort, ProviderRouter, StreamingPromptPort


class _FakeProvider:
    experimental = False

    def __init__(self, name: str, *, reply: str = "ok", error: Exception | None = None, ready: bool = True) -> None:
        self.name = name
        self._reply = reply
        self._error = error
        self._ready = ready
        self.calls: list[list[ChatMessage]] = []

    def is_ready(self) -> bool:
        return self._ready

    async def complete(
        self, messages: list[ChatMessage], *, json_schema: dict[str, Any] | None = None, max_tokens: int
    ) -> AIResult:
        self.calls.append(messages)
        if self._error is not None:
            raise self._error
        return AIResult(text=self._reply, provider_name=self.name, parsed_json={"ok": True} if json_schema else None)

    async def health(self) -> ProviderHealth:
        return ProviderHealth(self.name, "ok")


class _StreamingProvider(_FakeProvider):
    async def stream(self, messages: list[ChatMessage], *, max_tokens: int) -> AsyncIterator[str]:
        for piece in ("При", "вет"):
            yield piece


def _config(
    default: list[str], *, enabled: dict[str, bool] | None = None, connection: str = "api_key"
) -> ProvidersConfig:
    names = set(default)
    return ProvidersConfig(
        chains={"default": default, "complex": list(reversed(default))},
        enabled=enabled if enabled is not None else {name: True for name in names},
        claude_connection=connection,  # type: ignore[arg-type]
    )


def _router(providers: list[_FakeProvider], config: ProvidersConfig) -> ProviderRouter:
    return ProviderRouter(
        config_loader=lambda: config,
        factories={provider.name: (lambda model, provider=provider: provider) for provider in providers},
    )


@pytest.fixture(autouse=True)
def _fixed_persona(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router_module, "persona_instruction", lambda: "PERSONA")


@pytest.mark.parametrize(
    "error",
    [
        ProviderUnavailable("first", "down"),
        ProviderRateLimited("first", "429"),
        ProviderAuthError("first", "bad key"),
        ProviderBadResponse("first", "not json"),
        RuntimeError("unexpected"),
    ],
)
def test_complete_falls_back_on_every_failure_kind(error: Exception) -> None:
    first = _FakeProvider("first", error=error)
    second = _FakeProvider("second", reply="from second")
    router = _router([first, second], _config(["first", "second"]))

    result = asyncio.run(router.complete([{"role": "user", "content": "hi"}]))

    assert result.text == "from second"
    assert result.provider_name == "second"
    assert len(first.calls) == 1


def test_complete_logs_the_switch_reason(caplog: pytest.LogCaptureFixture) -> None:
    first = _FakeProvider("first", error=ProviderRateLimited("first", "limit"))
    second = _FakeProvider("second")
    router = _router([first, second], _config(["first", "second"]))

    with caplog.at_level(logging.WARNING):
        asyncio.run(router.complete([{"role": "user", "content": "hi"}]))

    assert any("switching to 'second'" in record.getMessage() for record in caplog.records)
    assert any("ProviderRateLimited" in record.getMessage() for record in caplog.records)


def test_complete_raises_with_every_failure_when_chain_is_exhausted() -> None:
    first = _FakeProvider("first", error=ProviderUnavailable("first", "down"))
    second = _FakeProvider("second", error=ProviderAuthError("second", "bad key"))
    router = _router([first, second], _config(["first", "second"]))

    with pytest.raises(AllProvidersFailed) as caught:
        asyncio.run(router.complete([{"role": "user", "content": "hi"}]))

    assert [name for name, _reason in caught.value.failures] == ["first", "second"]


def test_complete_with_no_usable_provider_raises() -> None:
    router = _router([_FakeProvider("first", ready=False)], _config(["first"]))

    with pytest.raises(AllProvidersFailed):
        asyncio.run(router.complete([{"role": "user", "content": "hi"}]))


def test_chain_skips_disabled_unready_and_unknown_providers() -> None:
    providers = [_FakeProvider("a"), _FakeProvider("b", ready=False), _FakeProvider("c")]
    config = _config(["a", "b", "ghost", "c"], enabled={"a": False, "b": True, "c": True, "ghost": True})
    router = _router(providers, config)

    assert [provider.name for provider in router.chain()] == ["c"]


def test_chain_skips_a_provider_whose_readiness_check_raises() -> None:
    class _Broken(_FakeProvider):
        def is_ready(self) -> bool:
            raise RuntimeError("keyring down")

    router = _router([_Broken("a"), _FakeProvider("b")], _config(["a", "b"]))

    assert [provider.name for provider in router.chain()] == ["b"]


def test_claude_connection_picks_exactly_one_claude_provider() -> None:
    providers = [_FakeProvider("anthropic_subscription"), _FakeProvider("anthropic_api")]
    names = ["anthropic_subscription", "anthropic_api"]

    via_key = _router(providers, _config(names, connection="api_key"))
    via_subscription = _router(providers, _config(names, connection="subscription"))

    assert [provider.name for provider in via_key.chain()] == ["anthropic_api"]
    assert [provider.name for provider in via_subscription.chain()] == ["anthropic_subscription"]


def test_complex_kind_uses_the_complex_chain() -> None:
    router = _router([_FakeProvider("a"), _FakeProvider("b")], _config(["a", "b"]))

    result = asyncio.run(router.complete([{"role": "user", "content": "hi"}], kind="complex"))

    assert result.provider_name == "b"


def test_json_schema_is_passed_through() -> None:
    router = _router([_FakeProvider("a")], _config(["a"]))

    result = asyncio.run(router.complete([{"role": "user", "content": "hi"}], json_schema={"type": "object"}))

    assert result.parsed_json == {"ok": True}


def test_ask_prepends_the_persona_as_a_system_message() -> None:
    provider = _FakeProvider("a")
    router = _router([provider], _config(["a"]))

    asyncio.run(router.ask("вопрос"))

    assert provider.calls[0] == [
        {"role": "system", "content": "PERSONA"},
        {"role": "user", "content": "вопрос"},
    ]


def test_ports_wrap_providers_and_only_streaming_ones_get_stream_prompt() -> None:
    router = _router([_FakeProvider("plain"), _StreamingProvider("streaming")], _config(["plain", "streaming"]))

    ports = router.ports()

    assert [type(port) for port in ports] == [PromptPort, StreamingPromptPort]
    assert not hasattr(ports[0], "stream_prompt")


def test_port_send_prompt_returns_text_and_stream_prompt_yields_deltas() -> None:
    streaming = _StreamingProvider("streaming", reply="целиком")
    router = _router([streaming], _config(["streaming"]))
    port = router.ports()[0]

    async def _collect() -> list[str]:
        return [piece async for piece in port.stream_prompt("hi")]  # type: ignore[attr-defined]

    assert asyncio.run(port.send_prompt("hi")) == "целиком"
    assert asyncio.run(_collect()) == ["При", "вет"]


def test_provider_instance_is_rebuilt_when_its_model_changes() -> None:
    built: list[str | None] = []

    def factory(model: str | None) -> _FakeProvider:
        built.append(model)
        return _FakeProvider("a")

    config_holder = {"config": ProvidersConfig(chains={"default": ["a"], "complex": []}, enabled={"a": True}, models={"a": "m1"})}
    router = ProviderRouter(config_loader=lambda: config_holder["config"], factories={"a": factory})

    router.chain()
    router.chain()
    config_holder["config"] = ProvidersConfig(chains={"default": ["a"], "complex": []}, enabled={"a": True}, models={"a": "m2"})
    router.chain()

    assert built == ["m1", "m2"]


def test_health_all_reports_disabled_and_failing_checks() -> None:
    class _Hanging(_FakeProvider):
        async def health(self) -> ProviderHealth:
            raise RuntimeError("boom")

    router = _router([_FakeProvider("ok"), _FakeProvider("off"), _Hanging("bad")], _config(["ok", "off", "bad"], enabled={"ok": True, "off": False, "bad": True}))

    statuses = {health.name: health.status for health in asyncio.run(router.health_all())}

    assert statuses == {"ok": "ok", "off": "disabled", "bad": "unavailable"}
