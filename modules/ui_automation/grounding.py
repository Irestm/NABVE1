from __future__ import annotations

import json
import re
from typing import Any

from core.ai_adapter_chain import local_first_chain
from core.logger import get_logger
from modules.ui_automation.domain import ACTIONS, UIElement, UIStep

logger = get_logger(__name__)

# A hard cap on how many actions one voice instruction can turn into — this
# is grounding a short spoken command, not a multi-minute macro.
MAX_STEPS = 5

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


def _build_prompt(window_title: str, elements: list[UIElement], raw_instruction: str) -> str:
    listing = "; ".join(f'{e.index}: [{e.role}] "{e.name}"' for e in elements if e.name)
    return (
        f'Пользователь голосом попросил выполнить действие в активном окне "{window_title}": '
        f'"{raw_instruction}". Вот пронумерованный список видимых элементов интерфейса этого окна: '
        f"{listing}. Определи, что нужно сделать — один или несколько шагов подряд. Каждый шаг — это "
        "либо клик по элементу из списка (укажи его номер в target_index), либо ввод текста туда, куда "
        "сейчас направлен фокус (обычно сразу после клика в текстовое поле), либо нажатие одной "
        "клавиши (например Enter, Escape, Tab). Если ни один элемент не подходит для инструкции — "
        'верни пустой список шагов. Ответь ТОЛЬКО JSON-объектом без пояснений, строго в формате '
        '{"steps": [{"action": "click", "target_index": <номер>}, '
        '{"action": "type_text", "text": "<текст>"}, {"action": "press_key", "key": "<клавиша>"}]}.'
    )


def _parse_step(raw_step: Any, elements_by_index: dict[int, UIElement]) -> UIStep | None:
    if not isinstance(raw_step, dict):
        return None
    action = raw_step.get("action")
    if action not in ACTIONS:
        return None

    if action == "click":
        target_index = raw_step.get("target_index")
        if not isinstance(target_index, int) or isinstance(target_index, bool):
            return None
        element = elements_by_index.get(target_index)
        if element is None:
            return None
        return UIStep(action="click", element=element)

    if action == "type_text":
        text = raw_step.get("text")
        if not isinstance(text, str) or not text:
            return None
        return UIStep(action="type_text", text=text)

    key = raw_step.get("key")
    if not isinstance(key, str) or not key:
        return None
    return UIStep(action="press_key", key=key)


def _parse_grounding(raw: str, elements: list[UIElement]) -> list[UIStep] | None:
    match = _JSON_OBJECT_PATTERN.search(raw)
    if not match:
        logger.warning("UI grounding returned no JSON object")
        return None

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("UI grounding returned invalid JSON")
        return None

    if not isinstance(parsed, dict):
        return None
    raw_steps = parsed.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps or len(raw_steps) > MAX_STEPS:
        return None

    elements_by_index = {element.index: element for element in elements}
    steps: list[UIStep] = []
    for raw_step in raw_steps:
        step = _parse_step(raw_step, elements_by_index)
        if step is None:
            # Any single structurally-invalid step rejects the whole
            # response rather than silently dropping it and running a
            # partial/different action sequence than the model intended.
            return None
        steps.append(step)

    return steps


async def ground(window_title: str, elements: list[UIElement], raw_instruction: str) -> list[UIStep] | None:
    """Tries to map `raw_instruction` (free text captured by
    core/voice/intent.py's _UI_ACTION_PATTERNS, or extracted by the AI
    classifier for unpatterned phrasing) to a short sequence of concrete UI
    steps against `elements` (see
    modules.ui_automation.atspi_adapter.AtspiElementInspector). Mirrors
    modules.app_catalog.resolver.resolve()'s shape: a numbered-candidate
    prompt, JSON-only response, regex-extracted + json.loads +
    graceful-None-on-failure parsing, tried across local_first_chain()'s
    adapters in order. Returns None if there's nothing to offer (no
    elements at all, or every adapter failed/produced an unusable
    response) — the caller then falls back to an ordinary "не поняла
    команду"."""
    if not elements:
        return None

    prompt = _build_prompt(window_title, elements, raw_instruction)
    for adapter in local_first_chain():
        try:
            raw = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            logger.warning("UI grounding adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue
        steps = _parse_grounding(raw, elements)
        if steps:
            return steps

    return None
