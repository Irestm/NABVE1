from __future__ import annotations

from dataclasses import dataclass

import pytest

from core.message_bus import Event, MessageBus


@dataclass(frozen=True)
class _Pinged(Event):
    value: int


async def test_publish_calls_subscribed_handlers_in_order() -> None:
    bus = MessageBus()
    received: list[int] = []

    async def handler_a(event: _Pinged) -> None:
        received.append(event.value)

    async def handler_b(event: _Pinged) -> None:
        received.append(event.value * 10)

    bus.subscribe(_Pinged, handler_a)
    bus.subscribe(_Pinged, handler_b)

    await bus.publish(_Pinged(value=1))

    assert received == [1, 10]


async def test_publish_with_no_subscribers_is_a_noop() -> None:
    bus = MessageBus()
    await bus.publish(_Pinged(value=1))  # must not raise


async def test_a_failing_handler_does_not_stop_other_handlers() -> None:
    bus = MessageBus()
    received: list[int] = []

    async def failing_handler(event: _Pinged) -> None:
        raise RuntimeError("boom")

    async def surviving_handler(event: _Pinged) -> None:
        received.append(event.value)

    bus.subscribe(_Pinged, failing_handler)
    bus.subscribe(_Pinged, surviving_handler)

    await bus.publish(_Pinged(value=42))  # must not raise

    assert received == [42]


async def test_only_handlers_for_the_exact_event_type_are_called() -> None:
    bus = MessageBus()

    @dataclass(frozen=True)
    class _OtherEvent(Event):
        pass

    received: list[int] = []

    async def handler(event: _Pinged) -> None:
        received.append(event.value)

    bus.subscribe(_Pinged, handler)
    await bus.publish(_OtherEvent())

    assert received == []
