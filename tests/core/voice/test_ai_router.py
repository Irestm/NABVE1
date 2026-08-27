from __future__ import annotations

import pytest

import core.ai_adapter_chain as ai_adapter_chain
import core.voice.ai_router as ai_router
from core.voice.ai_router import is_degenerate_answer
from modules.ai_bridge.intent_classifier import ClassificationResult


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
    # Simple-query candidate_chain() prepends the user's own Gemini API key
    # adapter when one happens to be configured (see _gemini_candidate in
    # core/ai_adapter_chain.py) - this test is about the local/cloud
    # fallback shape, not that, so it must not depend on whatever's
    # actually sitting in this machine's keyring right now.
    monkeypatch.setattr(ai_adapter_chain.api_providers, "get_gemini_adapter", lambda: None)
    assert ai_router._candidate_adapters("hello") == ["cloud"]


def test_candidate_adapters_tries_local_first_for_simple_query(monkeypatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: "local")
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: "cloud")
    monkeypatch.setattr(ai_adapter_chain.api_providers, "get_gemini_adapter", lambda: None)
    assert ai_router._candidate_adapters("простой вопрос") == ["local", "cloud"]


def test_candidate_adapters_tries_cloud_first_for_complex_query_but_keeps_local(monkeypatch) -> None:
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: "local")
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: "cloud")
    assert ai_router._candidate_adapters("погугли последние новости про AI") == ["cloud", "local"]


# --- resolve_free_text's on_progress reporting ------------------------------


class _FakeAdapter:
    def __init__(self, name: str, *, answer: str | None = None, raises: bool = False) -> None:
        self.name = name
        self._answer = answer
        self._raises = raises

    async def send_prompt(self, prompt_text: str, *, fast_mode: bool = True) -> str:
        if self._raises:
            raise RuntimeError("adapter unavailable")
        return self._answer


async def test_resolve_free_text_reports_progress_for_each_adapter_tried(monkeypatch: pytest.MonkeyPatch) -> None:
    failing = _FakeAdapter("local", raises=True)
    succeeding = _FakeAdapter("ai_bridge", answer="Ответ от облака")
    monkeypatch.setattr(ai_router, "_candidate_adapters", lambda text: [failing, succeeding])

    async def fake_classify(text, commands, adapter, *, context_hint=None):
        return ClassificationResult(matched_command=None, is_direct_question=True, params={})

    monkeypatch.setattr(ai_router, "classify", fake_classify)

    async def fake_record_gap_candidate(text, bus) -> None:
        return None

    monkeypatch.setattr(ai_router, "_record_gap_candidate", fake_record_gap_candidate)
    monkeypatch.setattr(ai_router, "_with_memory_context", lambda text, context_hint=None: text)

    progress_calls: list[str] = []
    command, answer = await ai_router.resolve_free_text(
        "вопрос", [], on_progress=progress_calls.append
    )

    assert command is None
    assert answer == "Ответ от облака"
    assert progress_calls == ["local", "local", "ai_bridge"]


# Regression for the "assistant lies about doing something" bug found
# live: a rate-limited/erroring classify() call used to be treated exactly
# like a genuine "this is a question" verdict, so resolve_free_text went on
# to ask a fallback adapter to just answer the (mis-transcribed, command-
# shaped) text conversationally — which could return a plausible "sure,
# done!" reply with no command ever dispatched. classification_failed must
# short-circuit straight to (None, None) instead, so the caller reports an
# honest "didn't understand" (see core/voice/pipeline.py's not_understood).
async def test_resolve_free_text_reports_unhandled_when_classification_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    would_be_asked = _FakeAdapter("local", answer="Хорошо, уже сделано!")
    monkeypatch.setattr(ai_router, "_candidate_adapters", lambda text: [would_be_asked])

    async def fake_classify(text, commands, adapter, *, context_hint=None):
        return ClassificationResult(
            matched_command=None, is_direct_question=True, params={}, classification_failed=True
        )

    monkeypatch.setattr(ai_router, "classify", fake_classify)

    command, answer = await ai_router.resolve_free_text("Понять громкость на ноутбуке до 10%", [])

    assert command is None
    assert answer is None


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


def test_with_memory_context_prepends_context_hint_when_no_facts_summary(monkeypatch) -> None:
    _mock_profile_context(monkeypatch, breath_effect="0")

    prompt = ai_router._with_memory_context("а сегодня какая была", "Обсуждали погоду в Киеве на завтра.")

    assert prompt.startswith("Обсуждали погоду в Киеве на завтра.")
    assert "а сегодня какая была" in prompt


def test_with_memory_context_combines_facts_summary_and_context_hint(monkeypatch) -> None:
    monkeypatch.setattr(ai_router.profile_service_layer, "get_context_facts", lambda uow, budget=10: ["x"])
    monkeypatch.setattr(ai_router.profile_service_layer, "format_context_summary", lambda facts: "Зовут Даниил.")
    monkeypatch.setattr(
        ai_router.profile_service_layer, "get_fact", lambda uow, key: None
    )

    prompt = ai_router._with_memory_context("вопрос", "Обсуждали погоду.")

    assert "Зовут Даниил." in prompt
    assert "Обсуждали погоду." in prompt
    assert prompt.index("Зовут Даниил.") < prompt.index("Обсуждали погоду.") < prompt.index("вопрос")


def test_with_memory_context_without_hint_is_unaffected(monkeypatch) -> None:
    _mock_profile_context(monkeypatch, breath_effect="0")

    assert ai_router._with_memory_context("привет") == "привет"


async def test_resolve_free_text_passes_context_hint_to_classify_and_memory_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression: an elliptical follow-up needs the previous exchange to
    # actually reach both the command classifier and the direct-answer
    # prompt, not just be accepted as a parameter nobody forwards.
    adapter = _FakeAdapter("local", answer="Ответ с учётом контекста")
    monkeypatch.setattr(ai_router, "_candidate_adapters", lambda text: [adapter])

    seen_classify_hint: list[str | None] = []

    async def fake_classify(text, commands, adapter, *, context_hint=None):
        seen_classify_hint.append(context_hint)
        return ClassificationResult(matched_command=None, is_direct_question=True, params={})

    monkeypatch.setattr(ai_router, "classify", fake_classify)

    async def fake_record_gap_candidate(text, bus) -> None:
        return None

    monkeypatch.setattr(ai_router, "_record_gap_candidate", fake_record_gap_candidate)

    seen_memory_hint: list[str | None] = []

    def fake_with_memory_context(text, context_hint=None):
        seen_memory_hint.append(context_hint)
        return text

    monkeypatch.setattr(ai_router, "_with_memory_context", fake_with_memory_context)

    hint = "Пользователь спросил про погоду в Киеве на завтра."
    command, answer = await ai_router.resolve_free_text("а сегодня какая была", [], context_hint=hint)

    assert answer == "Ответ с учётом контекста"
    assert seen_classify_hint == [hint]
    assert seen_memory_hint == [hint]


def test_breath_instruction_not_offered_on_most_prompts_even_when_enabled(monkeypatch) -> None:
    # Regression: the model was over-using the marker once it was offered on
    # every single prompt ("use it rarely" isn't reliable soft guidance for
    # a small local model) - the offer itself must be probabilistic so
    # "practically every answer" is structurally impossible.
    _mock_profile_context(monkeypatch, breath_effect="1")
    monkeypatch.setattr(ai_router.random, "random", lambda: 0.99)  # would always "lose" the roll

    assert ai_router.BREATH_MARKER not in ai_router._with_memory_context("Привет")
