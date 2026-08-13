from __future__ import annotations

import asyncio
import threading
from typing import Coroutine, TypeVar

from core.voice.barge_in import BargeInMonitor

T = TypeVar("T")


class TurnCancelled(Exception):
    """Raised by run_cancellable when the user said a stop phrase while the
    wrapped coroutine was still running. Callers let this propagate rather
    than catching it locally — see core/voice/pipeline.py's _handle_command,
    which has a single try/except around the whole resolve/dispatch
    sequence rather than one at every call site."""


async def _race(coro: "Coroutine[object, object, T]", stop_event: threading.Event) -> T:
    task = asyncio.create_task(coro)
    stop_waiter = asyncio.create_task(asyncio.to_thread(stop_event.wait))
    done, _pending = await asyncio.wait({task, stop_waiter}, return_when=asyncio.FIRST_COMPLETED)

    if task in done:
        # `stop_waiter` wraps a real OS thread blocked inside
        # threading.Event.wait() with no timeout (via asyncio.to_thread) —
        # merely cancelling the asyncio Task around it does NOT stop that
        # thread. asyncio.run()'s own cleanup blocks waiting for every
        # executor thread to finish, so without waking it here first, the
        # whole call would deadlock: the executor shutdown waits for this
        # thread, which waits for stop_event, which nothing ever sets.
        stop_event.set()
        try:
            await stop_waiter
        except asyncio.CancelledError:
            pass
        return task.result()

    # stop_event fired first — cancel the wrapped coroutine. This only
    # takes effect at its next await boundary, not mid-syscall, if `coro`
    # is currently blocked inside e.g. an asyncio.to_thread(...) call —
    # see run_cancellable's docstring for why that's an accepted,
    # sufficient limitation rather than a bug.
    task.cancel()
    try:
        await task
    except BaseException:  # noqa: BLE001 — swallow CancelledError *and* any
        # exception the coroutine happened to raise on its way out; either
        # way the user asked to stop, so TurnCancelled below is what
        # actually surfaces to the caller.
        pass
    raise TurnCancelled


def run_cancellable(coro: "Coroutine[object, object, T]", barge_in: BargeInMonitor, language: str) -> T:
    """Runs `coro` to completion — a drop-in replacement for a bare
    `asyncio.run(coro)` — except a BargeInMonitor listens on the mic for
    the whole duration, and hearing a stop phrase cancels `coro` and raises
    TurnCancelled instead of waiting for it to finish. Mirrors
    VoiceAssistantLoop._speak_safely's own bracket (fresh stop_event/
    interrupted pair, a dedicated monitor thread, torn down in `finally`),
    generalized from "wrap TTS playback" to "wrap any awaitable" — used to
    make command classification, parameter resolution, and dispatch()
    itself interruptible, not just the spoken reply.

    Deliberately NOT one long-lived monitor spanning a whole multi-step
    conversational turn: several callers of this function themselves record
    a follow-up answer from the user mid-turn (e.g. "did you mean X?"),
    which needs its own exclusive mic stream — a second stream open at the
    same time as this one would fight the first for the same audio device.
    Each call brackets its own monitor tightly instead, exactly like
    _speak_safely already does, so there's never more than one mic stream
    (and never two threads transcribing on `barge_in`'s shared model)
    active at once."""
    stop_event = threading.Event()
    interrupted = threading.Event()
    monitor_thread = threading.Thread(
        target=barge_in.run, args=(language, stop_event, interrupted), daemon=True
    )
    monitor_thread.start()
    try:
        return asyncio.run(_race(coro, stop_event))
    finally:
        stop_event.set()
        monitor_thread.join(timeout=1.0)
