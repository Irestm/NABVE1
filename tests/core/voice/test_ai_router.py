from __future__ import annotations

import core.ai_adapter_chain as ai_adapter_chain
import core.voice.ai_router as ai_router
from core.voice.ai_router import is_degenerate_answer


def test_empty_answer_is_degenerate() -> None:
    assert is_degenerate_answer("")
    assert is_degenerate_answer("   ")


def test_ordinary_answer_is_not_degenerate() -> None:
    assert not is_degenerate_answer("Столица Франции — Париж.")


def test_repeated_word_loop_is_degenerate() -> None:
    assert is_degenerate_answer("да " * 10)


def test_short_repetition_is_not_degenerate() -> None:
    assert not is_degenerate_answer("очень очень интересный вопрос")


def test_candidate_adapters_uses_cloud_only_when_local_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: None)
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: "cloud")
    assert ai_router._candidate_adapters("hello") == ["cloud"]


def test_candidate_adapters_tries_local_first_for_simple_query(monkeypatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: "local")
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: "cloud")
    assert ai_router._candidate_adapters("простой вопрос") == ["local", "cloud"]


def test_candidate_adapters_tries_cloud_first_for_complex_query_but_keeps_local(monkeypatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: "local")
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: "cloud")
    assert ai_router._candidate_adapters("погугли последние новости про AI") == ["cloud", "local"]


# --- _with_memory_context's breath-marker offer ----------------------------


def _mock_profile_context(monkeypatch, *, breath_effect: str | None) -> None:
    monkeypatch.setattr(ai_router.profile_service_layer, "get_context_facts", lambda uow, budget=10: [])
    monkeypatch.setattr(ai_router.profile_service_layer, "format_context_summary", lambda facts: None)
    monkeypatch.setattr(
        ai_router.profile_service_layer,
        "get_fact",
        lambda uow, key: breath_effect if key == ai_router.BREATH_EFFECT_KEY else None,
    )


def test_breath_instruction_never_offered_when_effect_disabled(monkeypatch) -> None:
    _mock_profile_context(monkeypatch, breath_effect="0")
    monkeypatch.setattr(ai_router.random, "random", lambda: 0.0)  # would always "win" the roll if reached

    assert ai_router.BREATH_MARKER not in ai_router._with_memory_context("Привет")


def test_breath_instruction_offered_when_effect_enabled_and_roll_succeeds(monkeypatch) -> None:
    _mock_profile_context(monkeypatch, breath_effect="1")
    monkeypatch.setattr(ai_router.random, "random", lambda: 0.0)

    assert ai_router.BREATH_MARKER in ai_router._with_memory_context("Привет")


def test_breath_instruction_not_offered_on_most_prompts_even_when_enabled(monkeypatch) -> None:
    # Regression: the model was over-using the marker once it was offered on
    # every single prompt ("use it rarely" isn't reliable soft guidance for
    # a small local model) - the offer itself must be probabilistic so
    # "practically every answer" is structurally impossible.
    _mock_profile_context(monkeypatch, breath_effect="1")
    monkeypatch.setattr(ai_router.random, "random", lambda: 0.99)  # would always "lose" the roll

    assert ai_router.BREATH_MARKER not in ai_router._with_memory_context("Привет")
