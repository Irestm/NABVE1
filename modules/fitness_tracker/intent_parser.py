from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from typing import Any

from core.logger import get_logger
from modules.ai_bridge.semantic_matcher import SemanticMatcher

logger = get_logger(__name__)

# Looser than modules.hardware_adaptive.command_classifier's 0.80: a
# false-negative here just means the utterance falls through to
# fitness_chat.py as a plain question (still answered, just not logged as
# structured data), while a false positive at worst produces a clarifying
# follow-up question — neither is the "silently does something unintended"
# failure mode that justified 0.80 for immediately-executed system commands.
_SIMILARITY_THRESHOLD = 0.62


class IntentCategory(str, enum.Enum):
    WEIGHT = "weight"
    HEIGHT = "height"
    AGE = "age"
    SEX = "sex"
    MEASUREMENT = "measurement"
    MEAL = "meal"
    GOAL = "goal"
    QUESTION = "question"


@dataclass
class ParsedIntent:
    category: IntentCategory | None
    entities: dict[str, Any] = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)
    confidence: float = 0.0


# Example phrases per category, embedded once via the shared multilingual
# model (modules.ai_bridge.semantic_matcher) rather than matched against
# fixed regex templates — the task spec explicitly asks for meaning-based
# recognition here, unlike the rest of this app's rule-based command
# matching, since real phrasing varies too much to enumerate
# ("поменяй мой вес на 78" / "я сегодня вешу 78 кг" / "весы показали 78" /
# "стал 78 кг" must all land on the same category).
_CATALOG: dict[str, tuple[str, ...]] = {
    IntentCategory.WEIGHT.value: (
        "поменяй мой вес на 78", "я сегодня вешу 78 кг", "весы показали 78",
        "вес 78 килограмм записывай", "стал 78 кг", "запиши вес 82",
        "мой текущий вес 90 кг", "похудел до 70 килограмм",
    ),
    IntentCategory.HEIGHT.value: (
        "мой рост 180 см", "рост сто восемьдесят сантиметров", "я ростом 175",
        "запиши мой рост 182 сантиметра",
    ),
    IntentCategory.AGE.value: (
        "мне 30 лет", "мне исполнилось 25", "запиши мой возраст 28",
        "мой возраст 40 лет",
    ),
    IntentCategory.SEX.value: (
        "я мужчина", "я женщина", "запиши что я мужчина", "я парень", "я девушка",
    ),
    IntentCategory.MEASUREMENT.value: (
        "замерь бицепс 35 см", "обхват талии 80 сантиметров", "замерь грудь 100 см",
        "замерь бедро 55 см", "мой бицепс стал 36 сантиметров", "талия 75 см",
    ),
    IntentCategory.MEAL.value: (
        "я съел овсянку с бананом", "сейчас поел курицу с рисом, было грамм 300",
        "на завтрак было яйцо и тост", "я перекусил яблоком", "съел на обед суп",
        "выпил протеиновый коктейль",
    ),
    IntentCategory.GOAL.value: (
        "поставь цель набрать 5 кг до декабря", "хочу поднять 100 кг в жиме до конца года",
        "поставь цель похудеть на 10 кг", "моя цель подтягиваться 15 раз",
        "хочу накачать бицепс до 40 сантиметров",
    ),
    IntentCategory.QUESTION.value: (
        "сколько калорий в яблоке", "что мне лучше съесть перед тренировкой",
        "нормальный ли у меня вес", "как часто нужно тренироваться",
        "что такое индекс массы тела",
    ),
}

_NUMBER_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)")

_SEX_STEMS = (("мужчин", "male"), ("парен", "male"), ("женщин", "female"), ("девушк", "female"))

_BODY_PART_STEMS = (
    ("бицепс", "bicep"), ("трицепс", "tricep"), ("тали", "waist"), ("живот", "waist"),
    ("груд", "chest"), ("бедр", "thigh"), ("плеч", "shoulder"), ("икр", "calf"),
    ("запясть", "wrist"), ("шея", "neck"), ("шеи", "neck"),
)

_STRENGTH_GOAL_STEMS = ("жим", "присед", "тяг", "подтягив", "отжима")
_VOLUME_GOAL_STEMS = ("объём", "объем", "накачать", "нарастить")

_matcher = SemanticMatcher()
_matcher_built = False


def _ensure_matcher_built() -> bool:
    global _matcher_built
    if _matcher_built:
        return True
    _matcher_built = _matcher.build(_CATALOG)
    return _matcher_built


def _extract_number(text: str) -> float | None:
    match = _NUMBER_PATTERN.search(text)
    if match is None:
        return None
    return float(match.group(1).replace(",", "."))


def _extract_sex(text: str) -> str | None:
    for stem, value in _SEX_STEMS:
        if stem in text:
            return value
    return None


def _extract_body_part(text: str) -> str | None:
    for stem, value in _BODY_PART_STEMS:
        if stem in text:
            return value
    return None


def _infer_goal_type(text: str) -> str:
    from modules.fitness_tracker.domain import GoalType

    if any(stem in text for stem in _STRENGTH_GOAL_STEMS):
        return GoalType.STRENGTH.value
    if any(stem in text for stem in _VOLUME_GOAL_STEMS):
        return GoalType.VOLUME.value
    return GoalType.WEIGHT.value


def _parse_weight_or_height_or_age(category: IntentCategory, text: str, score: float, field_name: str) -> ParsedIntent:
    value = _extract_number(text)
    if value is None:
        return ParsedIntent(category=category, entities={}, missing_fields=[field_name], confidence=score)
    return ParsedIntent(category=category, entities={field_name: value}, confidence=score)


def _parse_sex(text: str, score: float) -> ParsedIntent:
    sex = _extract_sex(text)
    if sex is None:
        return ParsedIntent(category=IntentCategory.SEX, entities={}, missing_fields=["sex"], confidence=score)
    return ParsedIntent(category=IntentCategory.SEX, entities={"sex": sex}, confidence=score)


def _parse_measurement(text: str, score: float) -> ParsedIntent:
    body_part = _extract_body_part(text)
    value = _extract_number(text)
    missing = []
    if body_part is None:
        missing.append("body_part")
    if value is None:
        missing.append("value_cm")
    entities: dict[str, Any] = {}
    if body_part is not None:
        entities["body_part"] = body_part
    if value is not None:
        entities["value_cm"] = value
    return ParsedIntent(category=IntentCategory.MEASUREMENT, entities=entities, missing_fields=missing, confidence=score)


def _parse_meal(text: str, score: float) -> ParsedIntent:
    # Grams are a nice-to-have for estimate_from_text's accuracy, not a
    # blocking requirement — modules.fitness_tracker.meal_analyzer already
    # accepts grams=None and degrades its confidence accordingly, so there's
    # nothing to clarify here: the whole utterance is a usable description
    # either way, matching the task spec's own canonical example ("я съел
    # овсянку с бананом", no grams at all).
    grams = _extract_number(text)
    entities: dict[str, Any] = {"description": text}
    if grams is not None:
        entities["grams"] = grams
    return ParsedIntent(category=IntentCategory.MEAL, entities=entities, confidence=score)


def _parse_goal(text: str, score: float) -> ParsedIntent:
    entities: dict[str, Any] = {"description": text, "goal_type": _infer_goal_type(text)}
    target_value = _extract_number(text)
    if target_value is not None:
        entities["target_value"] = target_value
        entities["unit"] = "kg" if ("кг" in text or "килограм" in text) else None
    return ParsedIntent(category=IntentCategory.GOAL, entities=entities, confidence=score)


def parse(text: str) -> ParsedIntent:
    """Classifies `text` into an IntentCategory by meaning (not fixed
    phrasing) and extracts whatever entities that category needs. Returns
    category=None when nothing scores above threshold at all — the caller
    (core/voice/pipeline.py's fitness context resolver) treats that as "not
    a recognized fitness topic" and routes the utterance to
    modules.fitness_tracker.fitness_chat.answer_question instead, per the
    task spec ("если сказанное вообще не похоже ни на одну известную
    категорию... передавать в fitness_chat.py как вопрос")."""
    stripped = text.strip().lower()
    if not stripped:
        return ParsedIntent(category=None)

    if not _ensure_matcher_built():
        return ParsedIntent(category=None)

    match = _matcher.best_match(stripped)
    if match is None:
        return ParsedIntent(category=None)

    label, score = match
    if score < _SIMILARITY_THRESHOLD:
        logger.info(
            "Fitness intent parser: no confident match for %r (closest was '%s', score=%.3f < threshold=%.2f)",
            text, label, score, _SIMILARITY_THRESHOLD,
        )
        return ParsedIntent(category=None, confidence=score)

    category = IntentCategory(label)
    if category is IntentCategory.WEIGHT:
        return _parse_weight_or_height_or_age(category, stripped, score, "weight_kg")
    if category is IntentCategory.HEIGHT:
        return _parse_weight_or_height_or_age(category, stripped, score, "height_cm")
    if category is IntentCategory.AGE:
        return _parse_weight_or_height_or_age(category, stripped, score, "age")
    if category is IntentCategory.SEX:
        return _parse_sex(stripped, score)
    if category is IntentCategory.MEASUREMENT:
        return _parse_measurement(stripped, score)
    if category is IntentCategory.MEAL:
        return _parse_meal(stripped, score)
    if category is IntentCategory.GOAL:
        return _parse_goal(stripped, score)
    return ParsedIntent(category=IntentCategory.QUESTION, entities={"text": text}, confidence=score)
