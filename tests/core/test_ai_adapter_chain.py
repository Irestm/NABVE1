from __future__ import annotations

import core.ai_adapter_chain as ai_adapter_chain


def test_returns_cloud_only_when_no_local_adapter(monkeypatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: None)
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: "cloud")
    assert ai_adapter_chain.local_first_chain() == ["cloud"]


def test_returns_local_then_cloud_when_local_available(monkeypatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: "local")
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: "cloud")
    assert ai_adapter_chain.local_first_chain() == ["local", "cloud"]


class _FakeGroqAdapter:
    name = "groq_api"


def test_free_api_first_chain_matches_local_first_chain_without_groq_key(monkeypatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: "local")
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: "cloud")
    monkeypatch.setattr(ai_adapter_chain.api_providers, "get_adapter", lambda: None)
    assert ai_adapter_chain.free_api_first_chain() == ai_adapter_chain.local_first_chain()


def test_free_api_first_chain_prepends_groq_when_available_and_under_quota(monkeypatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: "local")
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: "cloud")
    monkeypatch.setattr(ai_adapter_chain.api_providers, "get_adapter", lambda: _FakeGroqAdapter())
    monkeypatch.setattr(ai_adapter_chain.quota_tracker, "is_near_limit", lambda name: False)
    chain = ai_adapter_chain.free_api_first_chain()
    assert [getattr(a, "name", a) for a in chain] == ["groq_api", "local", "cloud"]


def test_free_api_first_chain_skips_groq_when_near_quota_limit(monkeypatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: "local")
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: "cloud")
    monkeypatch.setattr(ai_adapter_chain.api_providers, "get_adapter", lambda: _FakeGroqAdapter())
    monkeypatch.setattr(ai_adapter_chain.quota_tracker, "is_near_limit", lambda name: True)
    assert ai_adapter_chain.free_api_first_chain() == ["local", "cloud"]
