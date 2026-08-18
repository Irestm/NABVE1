from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.logger import get_logger
from core.message_bus import MessageBus, message_bus
from modules.timer.events import TimerFired

logger = get_logger(__name__)


@dataclass
class _ActiveTimer:
    label: str
    task: asyncio.Task
    ends_at: datetime


# Module-level, matching the same "singleton dict of running background
# work" shape as modules.messaging's watched-contact snooze checker — a
# personal assistant has at most a handful of concurrent timers, never
# persisted across a restart (an in-flight countdown restarting from zero
# after a crash/update would be actively wrong, not just inconvenient).
_active_timers: dict[int, _ActiveTimer] = {}
_next_timer_id = 1

# One stopwatch at a time, same "simplest correct model for a single-user
# local app" reasoning as modules.board_games.ui_session's one active game.
_stopwatch_started_at: datetime | None = None


def _allocate_timer_id() -> int:
    global _next_timer_id
    value = _next_timer_id
    _next_timer_id += 1
    return value


async def _run_timer(timer_id: int, seconds: float, label: str, bus: MessageBus) -> None:
    try:
        await asyncio.sleep(seconds)
    except asyncio.CancelledError:
        return
    finally:
        _active_timers.pop(timer_id, None)
    await bus.publish(TimerFired(timer_id=timer_id, label=label, message=f"{label}: время вышло."))


def start_timer(seconds: float, label: str, bus: MessageBus = message_bus, now: datetime | None = None) -> int:
    timer_id = _allocate_timer_id()
    task = asyncio.create_task(_run_timer(timer_id, seconds, label, bus))
    _active_timers[timer_id] = _ActiveTimer(
        label=label, task=task, ends_at=(now or datetime.now()) + timedelta(seconds=seconds)
    )
    return timer_id


def cancel_timer(timer_id: int) -> bool:
    active = _active_timers.pop(timer_id, None)
    if active is None:
        return False
    active.task.cancel()
    return True


def list_active_timers(now: datetime | None = None) -> list[dict[str, object]]:
    reference = now or datetime.now()
    return [
        {
            "id": timer_id,
            "label": active.label,
            "remaining_seconds": max(0, int((active.ends_at - reference).total_seconds())),
        }
        for timer_id, active in _active_timers.items()
    ]


def start_stopwatch(now: datetime | None = None) -> None:
    global _stopwatch_started_at
    _stopwatch_started_at = now or datetime.now()


def stop_stopwatch(now: datetime | None = None) -> timedelta:
    global _stopwatch_started_at
    if _stopwatch_started_at is None:
        raise RuntimeError("Секундомер сначала нужно запустить.")
    elapsed = (now or datetime.now()) - _stopwatch_started_at
    _stopwatch_started_at = None
    return elapsed


def stopwatch_elapsed(now: datetime | None = None) -> timedelta | None:
    if _stopwatch_started_at is None:
        return None
    return (now or datetime.now()) - _stopwatch_started_at
