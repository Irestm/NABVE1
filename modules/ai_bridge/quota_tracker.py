from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date

from core.config import DATA_DIR
from modules.ai_bridge.state_store import StateStore

# Conservative, hardcoded thresholds deliberately well under Groq's actual
# free-tier rate limits (which vary by model and change over time without
# notice) — the goal is to stop offering the adapter BEFORE a request would
# get a 429, not react to one after the fact (a failed request in the
# critical path is itself extra latency, the exact thing this tier exists to
# avoid). In-memory only: resets on process restart, which just means one
# extra cautious minute right after a restart, not a correctness problem —
# see the plan's note that persistence is a "fuller version" item, not
# needed for the first slice.
_WINDOW_SECONDS = 60.0
_MAX_REQUESTS_PER_WINDOW = 20

_DAILY_STATE_DB_PATH = DATA_DIR / "ai_bridge" / "daily_quota.db"


@dataclass
class _ProviderUsage:
    request_times: list[float] = field(default_factory=list)


class QuotaTracker:
    """Tracks recent request timestamps per free-API provider name and
    answers "is it safe to use this provider right now" proactively. Not
    tied to any specific provider — modules/ai_bridge/api_providers.py is
    the only caller today, but any future free-API adapter can share this
    same tracker instance.

    The per-minute window above is deliberately in-memory (see its own
    comment); a provider with a real per-DAY cap as well (Gemini's free
    tier: ~10 RPM *and* ~500 RPD) needs that second count to survive a
    process restart, so is_near_daily_limit/record_daily_request are backed
    by StateStore instead — lazily, so a provider that never calls them
    (Groq, which only has the per-minute limit) never touches disk for it."""

    def __init__(self, daily_store: StateStore | None = None) -> None:
        self._usage: dict[str, _ProviderUsage] = {}
        self._daily_store = daily_store

    def _usage_for(self, provider: str) -> _ProviderUsage:
        return self._usage.setdefault(provider, _ProviderUsage())

    def is_near_limit(self, provider: str, limit: int = _MAX_REQUESTS_PER_WINDOW) -> bool:
        usage = self._usage_for(provider)
        cutoff = time.monotonic() - _WINDOW_SECONDS
        usage.request_times = [t for t in usage.request_times if t >= cutoff]
        return len(usage.request_times) >= limit

    def record_request(self, provider: str) -> None:
        self._usage_for(provider).request_times.append(time.monotonic())

    def _daily(self) -> StateStore:
        if self._daily_store is None:
            self._daily_store = StateStore(db_path=_DAILY_STATE_DB_PATH)
        return self._daily_store

    def _maybe_reset_daily(self, provider: str) -> None:
        store = self._daily()
        today = date.today().isoformat()
        if store.get(f"{provider}:date") != today:
            store.set(f"{provider}:date", today)
            store.set(f"{provider}:count", "0")

    def daily_count(self, provider: str) -> int:
        self._maybe_reset_daily(provider)
        return int(self._daily().get(f"{provider}:count") or "0")

    def record_daily_request(self, provider: str) -> None:
        self._maybe_reset_daily(provider)
        self._daily().set(f"{provider}:count", str(self.daily_count(provider) + 1))

    def is_near_daily_limit(self, provider: str, limit: int) -> bool:
        return self.daily_count(provider) >= limit


quota_tracker = QuotaTracker()
