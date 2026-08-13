from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from core.logger import get_logger
from core.models import CommandDescriptor
from modules.ai_bridge.provider_manager import ProviderManager

logger = get_logger(__name__)

# Above this ratio, a near-verbatim match to a command name is trusted without
# spending an AI round-trip on it (e.g. a typed command name, or a command
# name spoken almost exactly as registered).
_DIRECT_MATCH_SIMILARITY_THRESHOLD = 0.82

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True)
class ClassificationResult:
    matched_command: str | None
    is_direct_question: bool
    params: dict[str, str]


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\s']", "", text, flags=re.UNICODE).strip().lower()


def _best_direct_match(text: str, commands: list[CommandDescriptor]) -> tuple[str | None, float]:
    normalized = _normalize(text)
    if not normalized:
        return None, 0.0
    best_name: str | None = None
    best_score = 0.0
    for command in commands:
        for candidate in (command.name, command.name.replace("_", " ")):
            score = SequenceMatcher(None, normalized, candidate.lower()).ratio()
            if score > best_score:
                best_score = score
                best_name = command.name
    return best_name, best_score


def _build_prompt(text: str, commands: list[CommandDescriptor]) -> str:
    command_list = "; ".join(f"{c.name} — {c.description}" for c in commands)
    return (
        f"Пользователь сказал: '{text}'. Вот список доступных команд системы: {command_list}. "
        "Определи, что хотел пользователь и какая команда из списка подходит, либо ответь, что "
        "это обычный вопрос, требующий ответа, а не команда. Если команда подходит и в её описании "
        "названы параметры (в скобках или по тексту) — извлеки их значения из фразы пользователя и "
        'верни в объекте "params" с ключами ровно такими же, как названы в описании; если значение '
        "какого-то параметра не удаётся определить из фразы, не включай этот ключ вовсе. "
        "Ответь ТОЛЬКО JSON-объектом без пояснений, строго в формате "
        '{"matched_command": "<имя_команды_или_null>", "params": {}, '
        '"is_direct_question": true|false}.'
    )


def _parse_classification(raw: str, commands: list[CommandDescriptor]) -> ClassificationResult:
    match = _JSON_OBJECT_PATTERN.search(raw)
    if not match:
        logger.warning("AI intent classification returned no JSON object; treating as a question")
        return ClassificationResult(matched_command=None, is_direct_question=True, params={})

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("AI intent classification returned invalid JSON; treating as a question")
        return ClassificationResult(matched_command=None, is_direct_question=True, params={})

    matched = parsed.get("matched_command")
    valid_names = {c.name for c in commands}
    if matched not in valid_names:
        matched = None

    raw_params = parsed.get("params")
    params = {str(key): str(value) for key, value in raw_params.items()} if isinstance(raw_params, dict) else {}

    is_question = bool(parsed.get("is_direct_question", matched is None))
    return ClassificationResult(matched_command=matched, is_direct_question=is_question, params=params)


async def classify(
    text: str,
    commands: list[CommandDescriptor],
    provider_manager: ProviderManager,
    *,
    similarity_threshold: float = _DIRECT_MATCH_SIMILARITY_THRESHOLD,
) -> ClassificationResult:
    """Classify free-text `text` (from voice or typed input) that didn't match
    any of the system's rule-based command patterns. A near-verbatim match
    against a registered command name is accepted directly, as a cheap
    optimization; otherwise the currently active AI provider is asked to pick
    between a command match and an ordinary question, via `provider_manager`
    using its fastest available mode.
    """
    best_name, score = _best_direct_match(text, commands)
    if best_name is not None and score >= similarity_threshold:
        return ClassificationResult(matched_command=best_name, is_direct_question=False, params={})

    prompt = _build_prompt(text, commands)
    try:
        raw = await provider_manager.send_prompt(prompt, fast_mode=True)
    except Exception:
        logger.exception("AI intent classification failed")
        return ClassificationResult(matched_command=None, is_direct_question=True, params={})

    return _parse_classification(raw, commands)
