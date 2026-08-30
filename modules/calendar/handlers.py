from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from core.dispatcher import CommandDispatcher
from modules.calendar import service_layer
from modules.calendar.domain import RecurrenceRule
from modules.calendar.uow import CalendarUnitOfWork

def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "да")


_RECURRENCE_LABELS: dict[RecurrenceRule, str] = {
    RecurrenceRule.NONE: "не повторяется",
    RecurrenceRule.DAILY: "каждый день",
    RecurrenceRule.WEEKLY: "каждую неделю",
    RecurrenceRule.MONTHLY: "каждый месяц",
    RecurrenceRule.YEARLY: "каждый год",
}


async def _handle_calendar_create_event(params: dict[str, Any]) -> dict[str, Any]:
    title = params.get("title")
    event_time_raw = params.get("event_time")
    if not title:
        raise ValueError("Не указано название события.")
    if not event_time_raw:
        raise ValueError("Не указано время события.")
    event_time = datetime.fromisoformat(event_time_raw)
    remind_before_minutes = int(params.get("remind_before_minutes", 0))
    color = params.get("color") or None
    category = params.get("category") or None
    critical = _parse_bool(params.get("critical", False))
    try:
        recurrence = RecurrenceRule(params.get("recurrence") or RecurrenceRule.NONE.value)
    except ValueError as exc:
        raise ValueError(f"Неизвестное правило повтора «{params.get('recurrence')}».") from exc

    event_id = await asyncio.to_thread(
        service_layer.create_event,
        CalendarUnitOfWork(),
        title,
        event_time,
        remind_before_minutes,
        color,
        category,
        recurrence,
        critical,
    )
    message = f"Событие «{title}» добавлено на {event_time.strftime('%d.%m.%Y %H:%M')}."
    if recurrence != RecurrenceRule.NONE:
        message += f" Повтор: {_RECURRENCE_LABELS[recurrence]}."
    if critical:
        message += " Критическое напоминание."
    return {
        "id": event_id,
        "title": title,
        "event_time": event_time.isoformat(),
        "remind_before_minutes": remind_before_minutes,
        "color": color,
        "category": category,
        "recurrence": recurrence.value,
        "critical": critical,
        "message": message,
    }


async def _handle_calendar_list_upcoming(params: dict[str, Any]) -> dict[str, Any]:
    limit = int(params.get("limit", 20))
    events = await asyncio.to_thread(service_layer.list_upcoming, CalendarUnitOfWork(), limit)
    if events:
        listed = "; ".join(f"{e.title} — {e.event_time.strftime('%d.%m %H:%M')}" for e in events)
        message = f"Ближайшие события: {listed}."
    else:
        message = "Ближайших событий нет."
    return {
        "events": [
            {
                "id": event.id,
                "title": event.title,
                "event_time": event.event_time.isoformat(),
                "remind_before_minutes": event.remind_before_minutes,
                "notified": event.notified,
                "color": event.color,
                "category": event.category,
                "recurrence": event.recurrence.value,
                "critical": event.critical,
            }
            for event in events
        ],
        "message": message,
    }


async def _handle_calendar_delete_event(params: dict[str, Any]) -> dict[str, Any]:
    event_id = params.get("event_id")
    if event_id is None:
        raise ValueError("Не указан идентификатор события.")
    deleted = await asyncio.to_thread(service_layer.delete_event, CalendarUnitOfWork(), int(event_id))
    return {"event_id": event_id, "deleted": deleted}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "calendar_create_event",
        _handle_calendar_create_event,
        dangerous=False,
        description=(
            "Создать событие/напоминание в календаре: название, время в ISO-8601, опционально "
            "remind_before_minutes, color (hex), category (текст-группа), recurrence "
            "(none/daily/weekly/monthly/yearly), critical (true — с полной блокировкой при "
            "срабатывании: пауза медиа, привлекающая анимация, ожидание голосового подтверждения)."
        ),
    )
    dispatcher.register(
        "calendar_list_upcoming",
        _handle_calendar_list_upcoming,
        dangerous=False,
        description="Показать ближайшие события календаря, сначала самые скорые.",
    )
    dispatcher.register(
        "calendar_delete_event",
        _handle_calendar_delete_event,
        dangerous=False,
        description="Удалить событие календаря по id (event_id).",
    )
