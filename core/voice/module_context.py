from __future__ import annotations

import time
from dataclasses import dataclass

# Generic "which module is the current voice utterance's first stop"
# primitive — introduced for modules.fitness_tracker.context_state but
# deliberately not fitness-specific, as a deposit for any future module that
# wants the same "давай про X" focused-listening behavior. Richer than
# modules.os_agent.session's bare bool (it needs a *name*, since more than
# one module can use this over time) but simpler than
# modules.board_games.ui_session (which stores a whole domain session
# object) — os_agent and board_games are NOT migrated onto this, they keep
# their own module-level singletons; see the fitness_tracker plan for why.
DEFAULT_TIMEOUT_SECONDS = 420


@dataclass
class _ActiveContext:
    name: str
    last_activity: float


_current: _ActiveContext | None = None


def activate(name: str) -> None:
    global _current
    _current = _ActiveContext(name=name, last_activity=time.monotonic())


def touch() -> None:
    """Resets the inactivity clock — called on every utterance handled while
    a context is active, so the timeout measures silence, not elapsed wall
    time since activation."""
    if _current is not None:
        _current.last_activity = time.monotonic()


def current(*, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> str | None:
    """Same lazy-expiry shape as core/dispatcher.py's PendingConfirmation
    TTL: no background watchdog thread, expiry is just checked whenever
    someone asks. A stale context silently clears itself here rather than
    lingering until some other code path notices."""
    global _current
    if _current is None:
        return None
    if time.monotonic() - _current.last_activity > timeout_seconds:
        _current = None
        return None
    return _current.name


def deactivate(name: str | None = None) -> bool:
    """`name` lets a caller say "leave the fitness context specifically" —
    a no-op (returns False) if some other context is active, guarding
    against one module's exit phrase accidentally clearing a different
    module's still-active context. Pass None to unconditionally clear
    whatever is active."""
    global _current
    if _current is None:
        return False
    if name is not None and _current.name != name:
        return False
    _current = None
    return True
