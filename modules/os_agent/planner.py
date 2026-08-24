from __future__ import annotations

import json
import re
from typing import Any

from core.logger import get_logger
from modules.ai_bridge import api_providers
from modules.ai_bridge.quota_tracker import quota_tracker
from modules.os_agent.domain import DECISION_KINDS, OS_AGENT_RPM_LIMIT, AgentDecision, AgentSession
from modules.ui_automation.domain import ACTIONS, UIElement, UIStep

logger = get_logger(__name__)

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)

_PROMPT_TEMPLATE = (
    'Ты выполняешь многошаговую задачу пользователя на его компьютере: "{task}". '
    'Сейчас активно окно "{window_title}". Вот пронумерованный список видимых элементов интерфейса: '
    "{listing}. "
    "Журнал уже сделанных/запланированных шагов этой задачи (может быть пустым): {journal}. "
    "Реши, что делать ДАЛЬШЕ — один следующий шаг, не всю задачу целиком. Варианты ответа: "
    '{{"kind": "step", "action": "click", "target_index": <номер>, "reason": "<кратко зачем>"}} — '
    "клик по элементу из списка; "
    '{{"kind": "step", "action": "type_text", "text": "<текст>", "reason": "<кратко зачем>"}} — '
    "ввод текста туда, куда сейчас направлен фокус; "
    '{{"kind": "step", "action": "press_key", "key": "<клавиша>", "reason": "<кратко зачем>"}} — '
    "нажатие одной клавиши (например Enter, Escape, Tab); "
    '{{"kind": "done", "reason": "<итог для пользователя>"}} — задача уже выполнена, дальше действовать не нужно; '
    '{{"kind": "stuck", "reason": "<что мешает>"}} — не видишь, как продолжить. '
    "Ответь ТОЛЬКО одним JSON-объектом без пояснений вне него."
)


def _build_prompt(task: str, window_title: str, elements: list[UIElement], journal: list[str]) -> str:
    listing = "; ".join(f'{e.index}: [{e.role}] "{e.name}"' for e in elements if e.name)
    journal_text = " ".join(journal) if journal else "(пусто)"
    return _PROMPT_TEMPLATE.format(task=task, window_title=window_title, listing=listing, journal=journal_text)


def _parse_step(raw: dict[str, Any], elements_by_index: dict[int, UIElement]) -> UIStep | None:
    action = raw.get("action")
    if action not in ACTIONS:
        return None
    if action == "click":
        target_index = raw.get("target_index")
        if not isinstance(target_index, int) or isinstance(target_index, bool):
            return None
        element = elements_by_index.get(target_index)
        return None if element is None else UIStep(action="click", element=element)
    if action == "type_text":
        text = raw.get("text")
        return UIStep(action="type_text", text=text) if isinstance(text, str) and text else None
    key = raw.get("key")
    return UIStep(action="press_key", key=key) if isinstance(key, str) and key else None


def _parse_decision(raw: str, elements: list[UIElement]) -> AgentDecision | None:
    match = _JSON_OBJECT_PATTERN.search(raw)
    if not match:
        logger.warning("os_agent planner returned no JSON object")
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("os_agent planner returned invalid JSON")
        return None
    if not isinstance(parsed, dict):
        return None

    kind = parsed.get("kind")
    if kind not in DECISION_KINDS:
        return None
    if kind in ("done", "stuck"):
        reason = parsed.get("reason")
        return AgentDecision(kind=kind, reason=reason if isinstance(reason, str) and reason else "")

    elements_by_index = {element.index: element for element in elements}
    step = _parse_step(parsed, elements_by_index)
    if step is None:
        return None
    reason = parsed.get("reason")
    return AgentDecision(kind="step", step=step, reason=reason if isinstance(reason, str) else "")


def _available_adapters() -> list[Any]:
    """Only the user's own configured Gemini/Claude key adapters, each
    gated by the stricter OS_AGENT_RPM_LIMIT against the shared
    modules.ai_bridge.quota_tracker counter — deliberately NOT
    core.ai_adapter_chain.candidate_chain(), whose fallback chain can reach
    the slow browser-automated ai_bridge providers, exactly what the agreed
    plan rules out for a decision loop ("браузерного фоллбэка НЕТ —
    слишком медленно для цикла решений")."""
    adapters = []
    gemini = api_providers.get_gemini_adapter()
    if gemini is not None and not quota_tracker.is_near_limit(gemini.name, limit=OS_AGENT_RPM_LIMIT):
        adapters.append(gemini)
    claude = api_providers.get_claude_adapter()
    if claude is not None and not quota_tracker.is_near_limit(claude.name, limit=OS_AGENT_RPM_LIMIT):
        adapters.append(claude)
    return adapters


def has_configured_key() -> bool:
    """Checked once at mode activation (core/voice/pipeline.py's
    _resolve_os_agent_start) — a hard refusal before the mode even turns on
    if neither key is configured, per the agreed plan."""
    return api_providers.get_gemini_adapter() is not None or api_providers.get_claude_adapter() is not None


def has_available_adapter() -> bool:
    """Checked by runner.py right after decide_next() returns None, to tell
    apart "every configured adapter is currently rate-limited" (outcome
    "throttled" — a key exists, it's just momentarily unavailable) from
    "every adapter produced an unusable response" (a real "stuck", not a
    throttle) — both surface as None from decide_next itself, but the two
    deserve different spoken wording."""
    return bool(_available_adapters())


async def decide_next(
    task: str, window_title: str, elements: list[UIElement], journal: list[str]
) -> AgentDecision | None:
    """Returns None when every configured adapter is currently throttled
    (or, in principle, none is configured at all — shouldn't happen given
    has_configured_key() already gated activation) — runner.py treats that
    exactly like hitting the step limit: stop and report whatever is queued
    so far, not an indefinite wait mid voice-turn."""
    adapters = _available_adapters()
    if not adapters:
        return None

    prompt = _build_prompt(task, window_title, elements, journal)
    for adapter in adapters:
        try:
            raw = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            logger.warning("os_agent planner adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue
        decision = _parse_decision(raw, elements)
        if decision is not None:
            return decision

    return None


async def explain(session: AgentSession) -> str | None:
    """The optional post-task "why did you do that" round
    (core/voice/pipeline.py::_offer_os_agent_explanation) — a short
    free-form explanation built from the same journal the loop itself used
    as context, via whichever configured adapter is available right now
    (independent of the per-step throttle: this runs at most once per task,
    after the loop is already done). Returns None if no adapter is
    available or every one of them failed, same graceful-degradation shape
    as decide_next above."""
    adapters = _available_adapters()
    if not adapters:
        return None

    journal_text = " ".join(session.journal) if session.journal else "(пусто)"
    prompt = (
        f'Кратко (1-2 предложения), простым языком объясни пользователю, почему для задачи '
        f'"{session.task}" был выбран именно такой план действий. Журнал шагов: {journal_text}. '
        "Ответь только самим объяснением, без вступлений."
    )
    for adapter in adapters:
        try:
            return (await adapter.send_prompt(prompt, fast_mode=True)).strip()
        except Exception as exc:
            logger.warning("os_agent explain adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue

    return None
