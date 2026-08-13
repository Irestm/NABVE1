from __future__ import annotations

import time
from dataclasses import dataclass, field

# Conservative, hardcoded thresholds deliberately well under Groq's actual
# free-tier rate limits (which vary by model and change without notice) —
# the goal is to stop offering the adapter BEFORE a request gets a 429,
# since a failed request in the critical path is itself the extra latency
# this tier exists to avoid. In-memory only: resets on process restart,
# which just costs one extra cautious minute, not a correctness problem.
_WINDOW_SECONDS = 60.0
_MAX_REQUESTS_PER_WINDOW = 20


@dataclass
class _ProviderUsage:
    request_times: list[float] = field(default_factory=list)


class QuotaTracker:
    """Tracks recent request timestamps per free-API provider name and
    answers "is it safe to use this provider right now" proactively. Not
    tied to any specific provider — modules/ai_bridge/api_providers.py is
    the only caller today, but any future free-API adapter can share this
    same tracker instance."""

    def __init__(self) -> None:
        self._usage: dict[str, _ProviderUsage] = {}

    def _usage_for(self, provider: str) -> _ProviderUsage:
        return self._usage.setdefault(provider, _ProviderUsage())

    def is_near_limit(self, provider: str) -> bool:
        usage = self._usage_for(provider)
        cutoff = time.monotonic() - _WINDOW_SECONDS
        usage.request_times = [t for t in usage.request_times if t >= cutoff]
        return len(usage.request_times) >= _MAX_REQUESTS_PER_WINDOW

    def record_request(self, provider: str) -> None:
        self._usage_for(provider).request_times.append(time.monotonic())


quota_tracker = QuotaTracker()
