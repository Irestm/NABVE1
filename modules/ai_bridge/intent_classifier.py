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
    # True only when the provider round-trip itself didn't produce a usable
    # judgment (raised, or returned unparseable output) — distinct from
    # is_direct_question=True, which means the model actually looked at the
    # text and decided it's a question. Callers must not treat this like a
    # real "it's a question" verdict: doing so previously routed a failed
    # classification straight into ai_router's conversational-answer path,
    # where a fallback adapter (e.g. the local model) would happily produce
    # a plausible-sounding "sure, done" reply for what was actually an
    # unclassified command — a hallucinated confirmation with no dispatch
    # behind it. See ai_router.resolve_free_text, which checks this flag to
    # give an honest "didn't understand" instead.
    classification_failed: bool = False


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


# One-shot examples, not just an instruction — found live: telling even a
# capable model "use the context to fill in missing parameters" in prose
# alone was unreliable (the small local model ignored it outright and
# answered "just a question" for a real "а сегодня какая была?" follow-up,
# despite the context being right there in the prompt); showing one worked
# example of the exact pattern (deliberately a *different* city/day than
# any real case, so this can't be mistaken for the model just parroting an
# answer that was spelled out for it) made the same weak model resolve the
# real case correctly on the very next attempt.
#
# A single weather-only example turned out not to generalize on its own —
# found live: a real "ладно, на 50" after a volume command ("подними
# громкость") still wasn't resolved from context, only ever "а вчера
# какая?"-shaped weather follow-ups were. A weak model pattern-matches the
# shown example's *domain*, not just its structure, so a second example
# from a different command family (volume, not weather) is what actually
# made that generalize — kept deliberately different numbers/command from
# any real case for the same parroting-proof reason as the first. Also
# demonstrates a case the first example doesn't: the follow-up can imply a
# *different* command than the one context names (an absolute value ("на
# 50") means set_volume, even though the prior turn's command was the
# relative change_volume) — filling in params from context isn't always
# just "reuse the same command with one field changed".
_CONTEXT_FEW_SHOT_EXAMPLES = (
    "Пример 1: контекст разговора — "
    '"пользователь спросил про погоду в Одессе на завтра, была вызвана команда '
    'weather_get(city=Одесса, when=tomorrow)". Новая фраза пользователя: "а послезавтра?". '
    'Правильный ответ: {"matched_command": "weather_get", "params": {"city": "Одесса", '
    '"when": "day_after_tomorrow"}, "is_direct_question": false} — потому что город не '
    "назван заново в новой фразе, значит он берётся из контекста, а сама фраза меняет только "
    "один параметр (when).\n"
    "Пример 2: контекст разговора — "
    '"пользователь сказал: «подними громкость». Ассистент выполнил команду change_volume с '
    'параметрами {\'delta_percent\': \'10\'}." Новая фраза пользователя: "ладно, на 50". '
    'Правильный ответ: {"matched_command": "set_volume", "params": {"percent": "50"}, '
    '"is_direct_question": false} — потому что фраза называет конкретное значение громкости, '
    "а не просит изменить её ещё на сколько-то, значит нужна другая команда из той же тематики "
    "(абсолютная установка, а не относительное изменение), хотя в контексте была указана "
    "предыдущая команда."
)


def _build_prompt(text: str, commands: list[CommandDescriptor], context_hint: str | None = None) -> str:
    command_list = "; ".join(f"{c.name} — {c.description}" for c in commands)
    context_section = (
        f"{_CONTEXT_FEW_SHOT_EXAMPLES}\n\n"
        f"Контекст этого же разговора (предыдущая реплика): {context_hint} "
        "Если новая фраза пользователя — это уточнение или продолжение той же темы без явного "
        "повторения предмета (например спросил про погоду в городе N, потом спросил только "
        '"а вчера?" или "а сколько градусов?") — по аналогии с примером выше используй этот '
        "контекст, чтобы понять, о чём речь, и подставь недостающие параметры из него. "
        if context_hint
        else ""
    )
    return (
        f"{context_section}Пользователь сказал: '{text}'. Вот список доступных команд системы: {command_list}. "
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
        logger.warning("AI intent classification returned no JSON object; treating as unclassified")
        return ClassificationResult(
            matched_command=None, is_direct_question=True, params={}, classification_failed=True
        )

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("AI intent classification returned invalid JSON; treating as unclassified")
        return ClassificationResult(
            matched_command=None, is_direct_question=True, params={}, classification_failed=True
        )

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
    context_hint: str | None = None,
) -> ClassificationResult:
    """Classify free-text `text` (from voice or typed input) that didn't match
    any of the system's rule-based command patterns. A near-verbatim match
    against a registered command name is accepted directly, as a cheap
    optimization; otherwise the currently active AI provider is asked to pick
    between a command match and an ordinary question, via `provider_manager`
    using its fastest available mode.

    `context_hint`, if given, is a one-line summary of the previous
    exchange within the same active voice session (see
    core/voice/pipeline.py's VoiceAssistantLoop._last_exchange) — lets an
    elliptical follow-up ("а сегодня какая была?" with no "погода" at all)
    resolve against the same command/params as the turn before it, instead
    of every utterance being classified in total isolation. Skipped
    entirely for the cheap direct-name-match path above, which doesn't
    need it.
    """
    best_name, score = _best_direct_match(text, commands)
    if best_name is not None and score >= similarity_threshold:
        return ClassificationResult(matched_command=best_name, is_direct_question=False, params={})

    prompt = _build_prompt(text, commands, context_hint)
    try:
        raw = await provider_manager.send_prompt(prompt, fast_mode=True)
    except Exception:
        logger.exception("AI intent classification failed")
        return ClassificationResult(
            matched_command=None, is_direct_question=True, params={}, classification_failed=True
        )

    return _parse_classification(raw, commands)
