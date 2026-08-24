from __future__ import annotations

from modules.fitness_tracker import announce, intent_parser, meal_analyzer, service_layer
from modules.fitness_tracker.domain import GoalType
from modules.fitness_tracker.intent_parser import IntentCategory, ParsedIntent

# Applies an already-classified ParsedIntent (see intent_parser.py) to the
# domain and produces the spoken confirmation — the "action" half of the
# voice flow, kept separate from intent_parser.py's pure classification so
# each stays independently testable (no service_layer/announce dependency
# needed to test parse() itself).


def merge_followup(parsed: ParsedIntent, followup_text: str) -> ParsedIntent:
    """Fills whichever fields were in `parsed.missing_fields` using the same
    lightweight extractors intent_parser.py's own categories use, from a
    one-shot spoken answer to a clarifying question (e.g. "Сколько
    примерно было граммов?" -> "триста"). Fields that still can't be filled
    stay in the returned ParsedIntent's missing_fields — the caller decides
    what to do with a still-incomplete result (see
    core/voice/pipeline.py::_resolve_fitness_clarify)."""
    entities = dict(parsed.entities)
    missing = list(parsed.missing_fields)

    for field_name in list(missing):
        if field_name in ("weight_kg", "height_cm", "age", "value_cm"):
            value = intent_parser._extract_number(followup_text)
            if value is not None:
                entities[field_name] = value
                missing.remove(field_name)
        elif field_name == "body_part":
            body_part = intent_parser._extract_body_part(followup_text)
            if body_part is not None:
                entities["body_part"] = body_part
                missing.remove(field_name)
        elif field_name == "sex":
            sex = intent_parser._extract_sex(followup_text)
            if sex is not None:
                entities["sex"] = sex
                missing.remove(field_name)

    return ParsedIntent(category=parsed.category, entities=entities, missing_fields=missing, confidence=parsed.confidence)


async def _apply_meal(entities: dict, language: str) -> str:
    description = entities["description"]
    grams = entities.get("grams")
    try:
        analysis = await meal_analyzer.estimate_from_text(description, grams)
    except meal_analyzer.MealAnalysisError as exc:
        # Still logged, just without a calorie estimate — a failed AI call
        # shouldn't lose the fact that the user ate something, only the
        # derived number.
        service_layer.log_meal(description, None, "low", "text")
        return announce.meal_analysis_failed_text(str(exc), language)

    macros = analysis["macros"]
    entry = service_layer.log_meal(
        analysis["description"],
        analysis["estimated_calories"],
        analysis["confidence"],
        "text",
        protein_g=macros.get("protein_g"),
        fat_g=macros.get("fat_g"),
        carbs_g=macros.get("carbs_g"),
    )
    return announce.meal_logged_text(entry.description, entry.estimated_calories, language)


async def apply_intent(parsed: ParsedIntent, language: str) -> str:
    """Applies a fully-resolved ParsedIntent (no remaining missing_fields)
    to the domain, returning the spoken confirmation. Callers must not pass
    a ParsedIntent with a non-empty missing_fields or category=None — see
    core/voice/pipeline.py's fitness resolver for how those are routed
    instead (to _resolve_fitness_clarify / fitness_chat.answer_question)."""
    category = parsed.category
    entities = parsed.entities

    if category is IntentCategory.WEIGHT:
        snapshot = service_layer.update_weight(entities["weight_kg"])
        return announce.weight_recorded_text(snapshot.weight_kg, language)
    if category is IntentCategory.HEIGHT:
        snapshot = service_layer.update_height(entities["height_cm"])
        return announce.height_recorded_text(snapshot.height_cm, language)
    if category is IntentCategory.AGE:
        snapshot = service_layer.update_age(int(entities["age"]))
        return announce.age_recorded_text(snapshot.age, language)
    if category is IntentCategory.SEX:
        snapshot = service_layer.update_sex(entities["sex"])
        return announce.sex_recorded_text(snapshot.sex, language)
    if category is IntentCategory.MEASUREMENT:
        measurement = service_layer.add_measurement(entities["body_part"], entities["value_cm"])
        return announce.measurement_recorded_text(measurement.body_part, measurement.value_cm, language)
    if category is IntentCategory.GOAL:
        goal = service_layer.add_goal(
            GoalType(entities["goal_type"]),
            entities["description"],
            target_value=entities.get("target_value"),
            unit=entities.get("unit"),
        )
        return announce.goal_recorded_text(goal.description, language)
    if category is IntentCategory.MEAL:
        return await _apply_meal(entities, language)

    raise ValueError(f"apply_intent called with an unsupported category: {category!r}")


def clarify_question_text(parsed: ParsedIntent, language: str) -> str:
    if "body_part" in parsed.missing_fields:
        return announce.clarify_body_part_text(language)
    if parsed.missing_fields:
        return announce.clarify_number_text(language)
    return announce.not_understood_in_context_text(language)
