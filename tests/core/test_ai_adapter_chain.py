from __future__ import annotations

import pytest

import core.ai_adapter_chain as ai_adapter_chain
from modules.ai_bridge.providers.config import ProvidersConfig


class _Provider:
    def __init__(self, name: str, *, experimental: bool = False) -> None:
        self.name = name
        self.experimental = experimental


class _Router:
    def __init__(self, chains: dict[str, list[_Provider]], config: ProvidersConfig | None = None) -> None:
        self._chains = chains
        self._config = config or ProvidersConfig(chains={"default": [], "complex": []}, enabled={})

    def chain(self, kind: str = "default") -> list[_Provider]:
        return list(self._chains[kind])

    def ports(self, kind: str = "default") -> list[_Provider]:
        return self.chain(kind)

    def ports_of(self, providers: list[_Provider]) -> list[_Provider]:
        return list(providers)

    def config(self) -> ProvidersConfig:
        return self._config


def _install(monkeypatch: pytest.MonkeyPatch, router: _Router) -> None:
    monkeypatch.setattr(ai_adapter_chain, "_router", lambda: router)


def test_candidate_chain_uses_default_chain_for_simple_text(monkeypatch: pytest.MonkeyPatch) -> None:
    simple = [_Provider("gemini_api"), _Provider("ollama")]
    _install(monkeypatch, _Router({"default": simple, "complex": [_Provider("anthropic_api")]}))

    assert [port.name for port in ai_adapter_chain.candidate_chain("привет")] == ["gemini_api", "ollama"]


def test_candidate_chain_uses_complex_chain_for_live_data_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _Router({"default": [_Provider("ollama")], "complex": [_Provider("anthropic_api")]}))

    assert [port.name for port in ai_adapter_chain.candidate_chain("погугли курс доллара")] == ["anthropic_api"]


def test_cloud_api_chain_drops_local_and_experimental_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    chain = [_Provider("ollama"), _Provider("gemini_api"), _Provider("browser_chain", experimental=True)]
    _install(monkeypatch, _Router({"default": chain, "complex": []}))

    assert [port.name for port in ai_adapter_chain.cloud_api_chain()] == ["gemini_api"]


def test_has_cloud_api_key_requires_an_enabled_provider_with_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    config = ProvidersConfig(chains={"default": [], "complex": []}, enabled={"gemini_api": False, "openai_api": True})
    _install(monkeypatch, _Router({"default": [], "complex": []}, config))
    keys = {"gemini_api": "g-key"}
    monkeypatch.setattr(ai_adapter_chain, "read_key", lambda name: keys.get(name))

    assert ai_adapter_chain.has_cloud_api_key() is False

    keys["openai_api"] = "o-key"
    assert ai_adapter_chain.has_cloud_api_key() is True
