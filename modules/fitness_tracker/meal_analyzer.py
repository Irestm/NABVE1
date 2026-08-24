from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from core.ai_adapter_chain import candidate_chain
from core.logger import get_logger
from modules.ai_bridge import vision
from modules.fitness_tracker.ethics_prompt import compose_fitness_prompt

logger = get_logger(__name__)

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
_ALLOWED_CONFIDENCE = ("high", "medium", "low")

_RESULT_INSTRUCTION = (
    "Ответь ТОЛЬКО одним JSON-объектом без пояснений вне него, со следующими полями: "
    '"description" (краткое описание блюда на русском), "estimated_calories" (число, примерная '
    'калорийность порции в ккал), "confidence" (строго одно из "high", "medium" или "low" — '
    "насколько ты уверен в оценке; используй \"low\", если состав или размер порции не вполне "
    'понятны), "macros" (объект с полями "protein_g", "fat_g", "carbs_g" — числа в граммах, если '
    "можешь их оценить, иначе не включай поле в объект)."
)


class MealAnalysisError(Exception):
    pass


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    match = _JSON_OBJECT_PATTERN.search(raw)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_confidence(value: Any) -> str:
    return value if value in _ALLOWED_CONFIDENCE else "medium"


def _normalize_macros(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    macros: dict[str, float] = {}
    for key in ("protein_g", "fat_g", "carbs_g"):
        number = value.get(key)
        if isinstance(number, (int, float)) and not isinstance(number, bool):
            macros[key] = float(number)
    return macros


def _build_result(parsed: dict[str, Any], fallback_description: str) -> dict[str, Any]:
    description = parsed.get("description")
    if not isinstance(description, str) or not description.strip():
        description = fallback_description
    calories = parsed.get("estimated_calories")
    estimated_calories = float(calories) if isinstance(calories, (int, float)) and not isinstance(calories, bool) else None
    return {
        "description": description.strip(),
        "estimated_calories": estimated_calories,
        "confidence": _normalize_confidence(parsed.get("confidence")),
        "macros": _normalize_macros(parsed.get("macros")),
    }


async def estimate_from_photo(image_path: Path) -> dict[str, Any]:
    """Sends the photo to Gemini's vision endpoint (modules.ai_bridge.vision
    — the same call shape modules.code_analysis uses for screenshots) and
    parses its structured JSON answer. Raises MealAnalysisError for every
    failure mode (no key configured, HTTP failure, unparseable response)."""
    try:
        image_bytes = image_path.read_bytes()
    except OSError as exc:
        raise MealAnalysisError(f"Не удалось прочитать файл фото: {exc}") from exc

    instruction = compose_fitness_prompt(
        f"Определи состав блюда на фото и примерную калорийность порции. {_RESULT_INSTRUCTION}"
    )
    try:
        raw = await vision.analyze_image(image_bytes, instruction)
    except vision.VisionAnalysisError as exc:
        raise MealAnalysisError(str(exc)) from exc

    parsed = _extract_json_object(raw)
    if parsed is None:
        logger.warning("Meal photo analysis: model reply had no parseable JSON object: %r", raw)
        raise MealAnalysisError("Не удалось разобрать ответ модели по фото еды.")
    return _build_result(parsed, fallback_description="Блюдо на фото")


async def estimate_from_text(description: str, grams: float | None = None) -> dict[str, Any]:
    """Delegates to the same text-adapter chain modules.code_analysis uses
    (core.ai_adapter_chain.candidate_chain) — no local nutrition database is
    maintained in this version (see the fitness_tracker plan for why), so
    every text estimate goes through an AI provider. When `grams` is given,
    the prompt asks for a precise per-100g-based lookup rather than a rough
    guess; when it's absent, the model is asked to assume a typical portion
    and reflect that uncertainty honestly via a lower confidence value."""
    portion_note = (
        f"Известный вес порции: {grams:g} грамм — используй реальные справочные данные о пищевой "
        "ценности на 100 грамм этого продукта и посчитай точно, не гадай."
        if grams is not None
        else "Вес порции не указан — оцени по типичному размеру порции и отрази это в поле confidence."
    )
    prompt = compose_fitness_prompt(
        f'Пользователь описал съеденное: "{description}". {portion_note} {_RESULT_INSTRUCTION}'
    )

    last_error: Exception | None = None
    for adapter in candidate_chain(description):
        try:
            raw = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            last_error = exc
            logger.warning("Meal text-analysis adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue
        parsed = _extract_json_object(raw)
        if parsed is not None:
            return _build_result(parsed, fallback_description=description)
        logger.warning("Meal text-analysis adapter '%s' returned no parseable JSON: %r", adapter.name, raw)

    logger.error("All AI adapters failed to analyze meal text: %s", last_error, exc_info=last_error)
    raise MealAnalysisError("Не удалось оценить калорийность — все AI-адаптеры недоступны.")
