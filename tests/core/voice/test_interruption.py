from __future__ import annotations

import asyncio
import threading
import time

import pytest

from core.voice.interruption import TurnCancelled, run_cancellable


class _FakeBargeIn:
    """Stands in for core.voice.barge_in.BargeInMonitor: same `.run(language,
    stop_event, interrupted)` shape, but fires on a timer instead of
    actually listening to a microphone."""

    def __init__(self, fire_after: float | None) -> None:
        # None means "never fires on its own" — only ever stopped
        # externally by run_cancellable's own `finally` block, mirroring a
        # stop phrase that's never said.
        self.fire_after = fire_after

    def run(self, language: str, stop_event: threading.Event, interrupted: threading.Event) -> None:
        if self.fire_after is None:
            stop_event.wait()
            return
        fired_externally = stop_event.wait(timeout=self.fire_after)
        if not fired_externally:
            interrupted.set()
            stop_event.set()


async def _quick_result() -> int:
    await asyncio.sleep(0.01)
    return 42


async def _slow_result() -> int:
    await asyncio.sleep(5)
    return 99


async def _raises() -> None:
    await asyncio.sleep(0.01)
    raise ValueError("boom")


def test_run_cancellable_returns_result_when_not_interrupted() -> None:
    result = run_cancellable(_quick_result(), _FakeBargeIn(fire_after=None), "ru")
    assert result == 42


def test_run_cancellable_raises_turn_cancelled_when_stop_phrase_heard() -> None:
    started_at = time.monotonic()
    with pytest.raises(TurnCancelled):
        run_cancellable(_slow_result(), _FakeBargeIn(fire_after=0.05), "ru")
    elapsed = time.monotonic() - started_at
    # The whole point: cancellation should land in well under _slow_result's
    # 5s sleep, not be forced to wait for it to finish anyway.
    assert elapsed < 1.0


def test_run_cancellable_propagates_the_coroutines_own_exception() -> None:
    with pytest.raises(ValueError, match="boom"):
        run_cancellable(_raises(), _FakeBargeIn(fire_after=None), "ru")


def test_run_cancellable_stops_the_monitor_thread_before_returning() -> None:
    # Regression guard: run_cancellable must not leak a running monitor
    # thread past its own return — the `finally` block should always join it.
    fake = _FakeBargeIn(fire_after=None)
    threads_before = threading.active_count()
    run_cancellable(_quick_result(), fake, "ru")
    # Give the joined thread a moment to fully unregister, then compare.
    time.sleep(0.05)
    assert threading.active_count() <= threads_before
