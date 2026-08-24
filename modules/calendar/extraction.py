from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

from core.ai_adapter_chain import candidate_chain
from core.logger import get_logger
from modules.calendar.domain import RecurrenceRule

logger = get_logger(__name__)

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
_DEFAULT_REMIND_BEFORE_MINUTES = 30
_VALID_RECURRENCE_VALUES = {rule.value for rule in RecurrenceRule}

_WEEKDAY_NAMES_RU = (
    "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье",
)


@dataclass(frozen=True)
class ExtractedEvent:
    title: str
    event_time: datetime
    remind_before_minutes: int
    # Both inferred from the same free text — "каждый день"/"по будням"
    # implies recurrence, "день рождения Иры" implies a "Дни рождения"
    # category — rather than always asking a separate clarifying question
    # for every single event, which would make one-off reminders (the
    # overwhelmingly common case) annoyingly slower to create by voice.
    recurrence: RecurrenceRule
    category: str | None


def _build_prompt(text: str, now: datetime) -> str:
    weekday = _WEEKDAY_NAMES_RU[now.weekday()]
    return (
        f'Сейчас {now.strftime("%Y-%m-%d %H:%M")} ({weekday}). Пользователь попросил записать в '
        f'планировщик: "{text}". Определи, ЧТО нужно сделать (короткое название события) и КОГДА — переведи '
        'относительные указания ("завтра", "в пятницу", "через час") в точную дату и время относительно '
        "текущего момента. Если время суток не названо явно, выбери разумное дневное время (например, 09:00). "
        "Если пользователь не сказал, за сколько минут напомнить — поставь 30. Если пользователь упомянул "
        'повтор ("каждый день", "каждую неделю", "каждый месяц", "каждый год", "по будням" и т.п.) — определи '
        'recurrence как одно из: "none", "daily", "weekly", "monthly", "yearly" (по умолчанию "none"). Если из '
        'события понятна общая категория/группа (например "день рождения" -> "Дни рождения") — укажи её в '
        "category, иначе null. Ответь ТОЛЬКО JSON-объектом без пояснений, строго в формате "
        '{"title": "...", "event_time": "YYYY-MM-DDTHH:MM:SS", "remind_before_minutes": <число>, '
        '"recurrence": "...", "category": "..." или null}. Если совсем нельзя понять, что и когда — верни '
        '{"title": null, "event_time": null, "remind_before_minutes": null, "recurrence": null, "category": null}.'
    )


def _parse_extraction(raw: str) -> ExtractedEvent | None:
    match = _JSON_OBJECT_PATTERN.search(raw)
    if not match:
        logger.warning("Event extraction returned no JSON object")
        return None

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("Event extraction returned invalid JSON")
        return None

    title = parsed.get("title")
    event_time_raw = parsed.get("event_time")
    if not isinstance(title, str) or not title.strip() or not isinstance(event_time_raw, str):
        return None

    try:
        event_time = datetime.fromisoformat(event_time_raw)
    except ValueError:
        logger.warning("Event extraction returned an unparseable event_time: %r", event_time_raw)
        return None

    remind = parsed.get("remind_before_minutes")
    if isinstance(remind, (int, float)) and not isinstance(remind, bool):
        remind_before_minutes = max(0, int(remind))
    else:
        remind_before_minutes = _DEFAULT_REMIND_BEFORE_MINUTES

    recurrence_raw = parsed.get("recurrence")
    recurrence = (
        RecurrenceRule(recurrence_raw) if recurrence_raw in _VALID_RECURRENCE_VALUES else RecurrenceRule.NONE
    )

    category_raw = parsed.get("category")
    category = category_raw.strip() if isinstance(category_raw, str) and category_raw.strip() else None

    return ExtractedEvent(
        title=title.strip(),
        event_time=event_time,
        remind_before_minutes=remind_before_minutes,
        recurrence=recurrence,
        category=category,
    )


async def extract_event(text: str, now: datetime | None = None) -> ExtractedEvent | None:
    """Turns free text like "купить молока завтра утром" into a structured
    (title, event_time, remind_before_minutes), via whichever AI adapter is
    available (local model first, then the ai_bridge cloud chain — see
    core.ai_adapter_chain), passing the current date/time so relative
    phrasing ("завтра", "в пятницу", "через час") resolves correctly.
    Returns None if every adapter failed, or the model itself couldn't make
    sense of the request (explicit null fields, bad JSON, an unparseable
    date) — the caller (core/voice/pipeline.py) then asks the user to
    clarify rather than guessing."""
    now = now or datetime.now()
    prompt = _build_prompt(text, now)

    for adapter in candidate_chain(text):
        try:
            raw = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            logger.warning("Event extraction adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue

        extracted = _parse_extraction(raw)
        if extracted is not None:
            return extracted

    return None
