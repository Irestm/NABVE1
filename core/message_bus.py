from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

from core.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Event:
    """Base class for domain events. Modules define their own frozen
    dataclasses subclassing this (e.g. `ReminderDue`, `UnhandledQuestionAsked`)
    to decouple the module that detects something happened from the
    module(s) that react to it — see
    https://www.cosmicpython.com/book/chapter_08_events_and_message_bus.html."""


EventT = TypeVar("EventT", bound=Event)
Handler = Callable[[EventT], Awaitable[None]]


class MessageBus:
    """Minimal pub/sub bus: publish() awaits every handler subscribed to the
    event's exact type, in registration order. Deliberately not full event
    sourcing/outbox — this app is a single local process, so "publish after
    commit, log failures, keep going" is enough."""

    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[Handler]] = {}

    def subscribe(self, event_type: type[EventT], handler: Handler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def publish(self, event: Event) -> None:
        handlers = self._handlers.get(type(event), [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception:
                # A subscriber failing must never break the publisher's own
                # use case (e.g. a notification adapter erroring shouldn't
                # fail the calendar-event creation that triggered it).
                logger.exception(
                    "Message bus handler '%s' failed while handling %s",
                    getattr(handler, "__qualname__", handler),
                    event,
                )


message_bus = MessageBus()
