from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from core.dispatcher import CommandDispatcher
from modules.calendar import service_layer
from modules.calendar.uow import CalendarUnitOfWork


async def _handle_calendar_create_event(params: dict[str, Any]) -> dict[str, Any]:
    title = params.get("title")
    event_time_raw = params.get("event_time")
    if not title:
        raise ValueError("Missing required parameter 'title'")
    if not event_time_raw:
        raise ValueError("Missing required parameter 'event_time'")
    event_time = datetime.fromisoformat(event_time_raw)
    remind_before_minutes = int(params.get("remind_before_minutes", 0))
    event_id = await asyncio.to_thread(
        service_layer.create_event, CalendarUnitOfWork(), title, event_time, remind_before_minutes
    )
    return {
        "id": event_id,
        "title": title,
        "event_time": event_time.isoformat(),
        "remind_before_minutes": remind_before_minutes,
        "message": f"Событие «{title}» добавлено на {event_time.strftime('%d.%m.%Y %H:%M')}.",
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
            }
            for event in events
        ],
        "message": message,
    }


async def _handle_calendar_delete_event(params: dict[str, Any]) -> dict[str, Any]:
    event_id = params.get("event_id")
    if event_id is None:
        raise ValueError("Missing required parameter 'event_id'")
    deleted = await asyncio.to_thread(service_layer.delete_event, CalendarUnitOfWork(), int(event_id))
    return {"event_id": event_id, "deleted": deleted}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "calendar_create_event",
        _handle_calendar_create_event,
        dangerous=False,
        description="Create a calendar event/reminder with a title, ISO-8601 event_time, and optional remind_before_minutes.",
    )
    dispatcher.register(
        "calendar_list_upcoming",
        _handle_calendar_list_upcoming,
        dangerous=False,
        description="List upcoming calendar events, soonest first.",
    )
    dispatcher.register(
        "calendar_delete_event",
        _handle_calendar_delete_event,
        dangerous=False,
        description="Delete a calendar event by id (event_id).",
    )
