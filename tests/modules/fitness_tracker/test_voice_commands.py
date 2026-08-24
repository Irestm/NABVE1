from __future__ import annotations

import pytest

from modules.fitness_tracker import meal_analyzer, service_layer, voice_commands
from modules.fitness_tracker.domain import BioProfileSnapshot, BodyMeasurement, Goal, GoalType, MealLogEntry
from modules.fitness_tracker.intent_parser import IntentCategory, ParsedIntent

# --- merge_followup -----------------------------------------------------


def test_merge_followup_fills_a_missing_number() -> None:
    parsed = ParsedIntent(category=IntentCategory.WEIGHT, entities={}, missing_fields=["weight_kg"])

    merged = voice_commands.merge_followup(parsed, "80")

    assert merged.entities["weight_kg"] == 80.0
    assert merged.missing_fields == []


def test_merge_followup_fills_a_missing_body_part() -> None:
    parsed = ParsedIntent(
        category=IntentCategory.MEASUREMENT, entities={"value_cm": 35.0}, missing_fields=["body_part"]
    )

    merged = voice_commands.merge_followup(parsed, "бицепс")

    assert merged.entities == {"value_cm": 35.0, "body_part": "bicep"}
    assert merged.missing_fields == []


def test_merge_followup_leaves_field_missing_when_still_unresolvable() -> None:
    parsed = ParsedIntent(category=IntentCategory.WEIGHT, entities={}, missing_fields=["weight_kg"])

    merged = voice_commands.merge_followup(parsed, "не знаю")

    assert merged.missing_fields == ["weight_kg"]


# --- apply_intent ---------------------------------------------------------


async def test_apply_intent_weight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service_layer, "update_weight", lambda value: BioProfileSnapshot(sex=None, age=None, height_cm=None, weight_kg=value, bmi=None)
    )

    result = await voice_commands.apply_intent(ParsedIntent(category=IntentCategory.WEIGHT, entities={"weight_kg": 78.0}), "ru")

    assert "78" in result


async def test_apply_intent_height(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service_layer, "update_height", lambda value: BioProfileSnapshot(sex=None, age=None, height_cm=value, weight_kg=None, bmi=None)
    )

    result = await voice_commands.apply_intent(ParsedIntent(category=IntentCategory.HEIGHT, entities={"height_cm": 180.0}), "ru")

    assert "180" in result


async def test_apply_intent_age(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service_layer, "update_age", lambda value: BioProfileSnapshot(sex=None, age=value, height_cm=None, weight_kg=None, bmi=None)
    )

    result = await voice_commands.apply_intent(ParsedIntent(category=IntentCategory.AGE, entities={"age": 30}), "ru")

    assert "30" in result


async def test_apply_intent_sex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service_layer, "update_sex", lambda value: BioProfileSnapshot(sex=value, age=None, height_cm=None, weight_kg=None, bmi=None)
    )

    result = await voice_commands.apply_intent(ParsedIntent(category=IntentCategory.SEX, entities={"sex": "male"}), "ru")

    assert "мужской" in result


async def test_apply_intent_measurement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service_layer, "add_measurement", lambda body_part, value_cm: BodyMeasurement(body_part=body_part, value_cm=value_cm)
    )

    result = await voice_commands.apply_intent(
        ParsedIntent(category=IntentCategory.MEASUREMENT, entities={"body_part": "bicep", "value_cm": 35.0}), "ru"
    )

    assert "bicep" in result and "35" in result


async def test_apply_intent_goal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service_layer,
        "add_goal",
        lambda goal_type, description, target_value=None, unit=None, deadline=None: Goal(
            goal_type=goal_type, description=description, target_value=target_value, unit=unit
        ),
    )

    result = await voice_commands.apply_intent(
        ParsedIntent(
            category=IntentCategory.GOAL,
            entities={"description": "набрать 5 кг", "goal_type": GoalType.WEIGHT.value, "target_value": 83.0, "unit": "kg"},
        ),
        "ru",
    )

    assert "набрать 5 кг" in result


async def test_apply_intent_meal_logs_and_announces_calories(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_estimate_from_text(description: str, grams: float | None = None) -> dict:
        return {"description": description, "estimated_calories": 350.0, "confidence": "medium", "macros": {}}

    monkeypatch.setattr(meal_analyzer, "estimate_from_text", fake_estimate_from_text)
    monkeypatch.setattr(
        service_layer,
        "log_meal",
        lambda description, estimated_calories, confidence, source, **kwargs: MealLogEntry(
            description=description, estimated_calories=estimated_calories, confidence=confidence, source=source
        ),
    )

    result = await voice_commands.apply_intent(
        ParsedIntent(category=IntentCategory.MEAL, entities={"description": "овсянка с бананом"}), "ru"
    )

    assert "овсянка с бананом" in result
    assert "350" in result


async def test_apply_intent_meal_still_logs_when_analysis_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_estimate_from_text(description: str, grams: float | None = None) -> dict:
        raise meal_analyzer.MealAnalysisError("нет ключа")

    monkeypatch.setattr(meal_analyzer, "estimate_from_text", fake_estimate_from_text)
    logged = {}

    def fake_log_meal(description, estimated_calories, confidence, source, **kwargs):
        logged["description"] = description
        logged["estimated_calories"] = estimated_calories
        return MealLogEntry(description=description, estimated_calories=estimated_calories, confidence=confidence, source=source)

    monkeypatch.setattr(service_layer, "log_meal", fake_log_meal)

    result = await voice_commands.apply_intent(
        ParsedIntent(category=IntentCategory.MEAL, entities={"description": "овсянка"}), "ru"
    )

    assert logged["description"] == "овсянка"
    assert logged["estimated_calories"] is None
    assert "нет ключа" in result


async def test_apply_intent_raises_for_question_category() -> None:
    with pytest.raises(ValueError):
        await voice_commands.apply_intent(ParsedIntent(category=IntentCategory.QUESTION), "ru")


# --- clarify_question_text -------------------------------------------------


def test_clarify_question_text_for_missing_body_part() -> None:
    text = voice_commands.clarify_question_text(
        ParsedIntent(category=IntentCategory.MEASUREMENT, missing_fields=["body_part"]), "ru"
    )
    assert "часть тела" in text


def test_clarify_question_text_for_missing_number() -> None:
    text = voice_commands.clarify_question_text(
        ParsedIntent(category=IntentCategory.WEIGHT, missing_fields=["weight_kg"]), "ru"
    )
    assert "число" in text


def test_clarify_question_text_falls_back_when_nothing_missing() -> None:
    text = voice_commands.clarify_question_text(ParsedIntent(category=None), "ru")
    assert text
