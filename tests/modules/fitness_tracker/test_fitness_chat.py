from __future__ import annotations

import pytest

from modules.fitness_tracker import fitness_chat, service_layer
from modules.fitness_tracker.domain import BioProfileSnapshot, Goal, GoalType, MealLogEntry
from modules.user_profile import service_layer as profile_service_layer


class _FakeAdapter:
    def __init__(self, name: str, reply: str | None = None, should_raise: bool = False) -> None:
        self.name = name
        self._reply = reply
        self._should_raise = should_raise

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
        if self._should_raise:
            raise RuntimeError("adapter down")
        return self._reply or ""


@pytest.fixture(autouse=True)
def _reset_hint_state():
    fitness_chat.reset_api_key_hint()
    yield
    fitness_chat.reset_api_key_hint()


@pytest.fixture(autouse=True)
def _no_ai_keys_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(fitness_chat, "get_gemini_adapter", lambda: None)
    monkeypatch.setattr(fitness_chat, "get_claude_adapter", lambda: None)


# --- build_context_summary ---------------------------------------------------


def test_build_context_summary_is_none_when_nothing_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_layer, "get_current_bio_profile", lambda: None)
    monkeypatch.setattr(service_layer, "list_goals", lambda: [])
    monkeypatch.setattr(service_layer, "list_meals", lambda limit=None: [])

    assert fitness_chat.build_context_summary() is None


def test_build_context_summary_includes_profile_goals_and_meals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service_layer,
        "get_current_bio_profile",
        lambda: BioProfileSnapshot(sex="male", age=30, height_cm=180.0, weight_kg=78.0, bmi=24.1),
    )
    monkeypatch.setattr(
        service_layer,
        "list_goals",
        lambda: [Goal(goal_type=GoalType.WEIGHT, description="набрать 5 кг", achieved_at=None)],
    )
    monkeypatch.setattr(
        service_layer,
        "list_meals",
        lambda limit=None: [MealLogEntry(description="овсянка", estimated_calories=350.0, confidence="medium", source="text")],
    )

    summary = fitness_chat.build_context_summary()

    assert "78" in summary
    assert "набрать 5 кг" in summary
    assert "овсянка" in summary


def test_build_context_summary_excludes_achieved_goals(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime

    monkeypatch.setattr(service_layer, "get_current_bio_profile", lambda: None)
    monkeypatch.setattr(
        service_layer,
        "list_goals",
        lambda: [Goal(goal_type=GoalType.WEIGHT, description="старая цель", achieved_at=datetime.now())],
    )
    monkeypatch.setattr(service_layer, "list_meals", lambda limit=None: [])

    assert fitness_chat.build_context_summary() is None


# --- save_important_fact / _learn_from_chat ----------------------------------


def test_save_important_fact_tags_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = {}
    monkeypatch.setattr(
        profile_service_layer, "record_episodic_fact", lambda uow, key, value: recorded.update(key=key, value=value)
    )

    fitness_chat.save_important_fact("diet_preference", "вегетарианец")

    assert recorded == {"key": "fitness_diet_preference", "value": "вегетарианец"}


def test_learn_from_chat_saves_extracted_facts_with_the_fitness_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.voice.fact_extraction import ExtractedFact

    monkeypatch.setattr(fitness_chat, "extract_facts", lambda text, language: [ExtractedFact(key="name", value="Даниил")])
    saved = []
    monkeypatch.setattr(fitness_chat, "save_important_fact", lambda key, value: saved.append((key, value)))

    fitness_chat._learn_from_chat("меня зовут Даниил", "ru")

    assert saved == [("name", "Даниил")]


def test_learn_from_chat_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(text: str, language: str):
        raise RuntimeError("boom")

    monkeypatch.setattr(fitness_chat, "extract_facts", _boom)

    fitness_chat._learn_from_chat("что угодно", "ru")


# --- answer_question ----------------------------------------------------------


async def test_answer_question_returns_the_first_adapters_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fitness_chat, "candidate_chain", lambda text: [_FakeAdapter("a", reply="Ешь больше белка.")])
    monkeypatch.setattr(fitness_chat, "build_context_summary", lambda: None)

    result = await fitness_chat.answer_question("что мне есть перед тренировкой")

    assert result.startswith("Ешь больше белка.")


async def test_answer_question_falls_through_to_the_next_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    failing = _FakeAdapter("a", should_raise=True)
    working = _FakeAdapter("b", reply="Ответ.")
    monkeypatch.setattr(fitness_chat, "candidate_chain", lambda text: [failing, working])
    monkeypatch.setattr(fitness_chat, "build_context_summary", lambda: None)

    result = await fitness_chat.answer_question("вопрос")

    assert result.startswith("Ответ.")


async def test_answer_question_raises_when_every_adapter_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fitness_chat, "candidate_chain", lambda text: [_FakeAdapter("a", should_raise=True)])
    monkeypatch.setattr(fitness_chat, "build_context_summary", lambda: None)

    with pytest.raises(fitness_chat.FitnessChatError):
        await fitness_chat.answer_question("вопрос")


async def test_answer_question_appends_the_api_key_hint_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fitness_chat, "candidate_chain", lambda text: [_FakeAdapter("a", reply="Ответ.")])
    monkeypatch.setattr(fitness_chat, "build_context_summary", lambda: None)

    first = await fitness_chat.answer_question("вопрос", "ru")
    second = await fitness_chat.answer_question("вопрос", "ru")

    assert "ключ" in first
    assert "ключ" not in second


async def test_answer_question_omits_hint_when_a_key_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fitness_chat, "get_gemini_adapter", lambda: object())
    monkeypatch.setattr(fitness_chat, "candidate_chain", lambda text: [_FakeAdapter("a", reply="Ответ.")])
    monkeypatch.setattr(fitness_chat, "build_context_summary", lambda: None)

    result = await fitness_chat.answer_question("вопрос", "ru")

    assert result == "Ответ."


async def test_answer_question_includes_the_context_summary_in_the_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class _CapturingAdapter(_FakeAdapter):
        async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
            captured["prompt"] = text
            return "Ответ."

    monkeypatch.setattr(fitness_chat, "candidate_chain", lambda text: [_CapturingAdapter("a")])
    monkeypatch.setattr(fitness_chat, "build_context_summary", lambda: "Текущие показатели пользователя: вес 78 кг.")

    await fitness_chat.answer_question("сколько мне нужно белка")

    assert "78 кг" in captured["prompt"]
