from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from core.message_bus import MessageBus
from modules.timer import service_layer
from modules.timer.events import TimerFired


@pytest.fixture(autouse=True)
def _reset_module_state() -> None:
    service_layer._active_timers.clear()
    service_layer._stopwatch_started_at = None
    yield
    for active in list(service_layer._active_timers.values()):
        active.task.cancel()
    service_layer._active_timers.clear()
    service_layer._stopwatch_started_at = None


async def test_start_timer_fires_timer_fired_after_it_elapses() -> None:
    bus = MessageBus()
    received: list[TimerFired] = []

    async def handler(event: TimerFired) -> None:
        received.append(event)

    bus.subscribe(TimerFired, handler)

    timer_id = service_layer.start_timer(0.01, "Чай", bus=bus)
    await asyncio.sleep(0.05)

    assert received == [TimerFired(timer_id=timer_id, label="Чай", message="Чай: время вышло.")]
    assert timer_id not in service_layer._active_timers


async def test_cancel_timer_prevents_it_from_firing() -> None:
    bus = MessageBus()
    received: list[TimerFired] = []

    async def handler(event: TimerFired) -> None:
        received.append(event)

    bus.subscribe(TimerFired, handler)

    timer_id = service_layer.start_timer(0.02, "Чай", bus=bus)
    assert service_layer.cancel_timer(timer_id) is True
    await asyncio.sleep(0.05)

    assert received == []


def test_cancel_timer_returns_false_for_an_unknown_id() -> None:
    assert service_layer.cancel_timer(999) is False


async def test_list_active_timers_reports_remaining_time() -> None:
    now = datetime(2030, 1, 1, 12, 0, 0)
    service_layer.start_timer(120, "Пицца", now=now)

    active = service_layer.list_active_timers(now=now + timedelta(seconds=30))

    assert len(active) == 1
    assert active[0]["label"] == "Пицца"
    assert active[0]["remaining_seconds"] == 90


def test_stopwatch_start_stop_and_elapsed() -> None:
    now = datetime(2030, 1, 1, 12, 0, 0)

    assert service_layer.stopwatch_elapsed(now=now) is None

    service_layer.start_stopwatch(now=now)
    assert service_layer.stopwatch_elapsed(now=now + timedelta(seconds=10)) == timedelta(seconds=10)

    elapsed = service_layer.stop_stopwatch(now=now + timedelta(seconds=42))
    assert elapsed == timedelta(seconds=42)
    assert service_layer.stopwatch_elapsed(now=now) is None


def test_stop_stopwatch_without_starting_raises() -> None:
    with pytest.raises(RuntimeError, match="сначала нужно запустить"):
        service_layer.stop_stopwatch()
