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


# --- candidate_chain: Gemini (simple) / Claude (complex) --------------------


class _FakeGeminiAdapter:
    name = "gemini_api"


class _FakeClaudeAdapter:
    name = "claude_api"


def _base_chain(monkeypatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: "local")
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: "cloud")
    monkeypatch.setattr(ai_adapter_chain.api_providers, "get_adapter", lambda: None)


def test_candidate_chain_prepends_gemini_for_a_simple_query_when_configured(monkeypatch) -> None:
    _base_chain(monkeypatch)
    monkeypatch.setattr(ai_adapter_chain.local_ai, "is_complex_query", lambda text: False)
    gemini = _FakeGeminiAdapter()
    monkeypatch.setattr(ai_adapter_chain.api_providers, "get_gemini_adapter", lambda: gemini)
    monkeypatch.setattr(ai_adapter_chain.quota_tracker, "is_near_limit", lambda name, limit=None: False)
    monkeypatch.setattr(ai_adapter_chain.quota_tracker, "is_near_daily_limit", lambda name, limit: False)

    assert ai_adapter_chain.candidate_chain("простой вопрос") == [gemini, "local", "cloud"]


def test_candidate_chain_skips_gemini_when_no_key_configured(monkeypatch) -> None:
    _base_chain(monkeypatch)
    monkeypatch.setattr(ai_adapter_chain.local_ai, "is_complex_query", lambda text: False)
    monkeypatch.setattr(ai_adapter_chain.api_providers, "get_gemini_adapter", lambda: None)

    assert ai_adapter_chain.candidate_chain("простой вопрос") == ["local", "cloud"]


def test_candidate_chain_skips_gemini_when_near_the_per_minute_limit(monkeypatch) -> None:
    _base_chain(monkeypatch)
    monkeypatch.setattr(ai_adapter_chain.local_ai, "is_complex_query", lambda text: False)
    monkeypatch.setattr(ai_adapter_chain.api_providers, "get_gemini_adapter", lambda: _FakeGeminiAdapter())
    monkeypatch.setattr(ai_adapter_chain.quota_tracker, "is_near_limit", lambda name, limit=None: True)

    assert ai_adapter_chain.candidate_chain("простой вопрос") == ["local", "cloud"]


def test_candidate_chain_skips_gemini_when_near_the_daily_limit(monkeypatch) -> None:
    _base_chain(monkeypatch)
    monkeypatch.setattr(ai_adapter_chain.local_ai, "is_complex_query", lambda text: False)
    monkeypatch.setattr(ai_adapter_chain.api_providers, "get_gemini_adapter", lambda: _FakeGeminiAdapter())
    monkeypatch.setattr(ai_adapter_chain.quota_tracker, "is_near_limit", lambda name, limit=None: False)
    monkeypatch.setattr(ai_adapter_chain.quota_tracker, "is_near_daily_limit", lambda name, limit: True)

    assert ai_adapter_chain.candidate_chain("простой вопрос") == ["local", "cloud"]


def test_candidate_chain_prepends_claude_for_a_complex_query_when_configured(monkeypatch) -> None:
    _base_chain(monkeypatch)
    monkeypatch.setattr(ai_adapter_chain.local_ai, "is_complex_query", lambda text: True)
    claude = _FakeClaudeAdapter()
    monkeypatch.setattr(ai_adapter_chain.api_providers, "get_claude_adapter", lambda: claude)

    assert ai_adapter_chain.candidate_chain("сложный вопрос") == [claude, "cloud", "local"]


def test_candidate_chain_skips_claude_when_no_key_configured(monkeypatch) -> None:
    _base_chain(monkeypatch)
    monkeypatch.setattr(ai_adapter_chain.local_ai, "is_complex_query", lambda text: True)
    monkeypatch.setattr(ai_adapter_chain.api_providers, "get_claude_adapter", lambda: None)

    assert ai_adapter_chain.candidate_chain("сложный вопрос") == ["cloud", "local"]
