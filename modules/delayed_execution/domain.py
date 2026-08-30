from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class DelayedCommandStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class DelayedCommand:
    # The dispatcher command resolved from the spoken remainder at schedule
    # time (not re-resolved on firing) — a delayed command is decided once,
    # when the user asks for it, so "открой браузер через 10 минут" can't
    # silently mean something else ten minutes later.
    command_name: str
    command_params: dict[str, Any]
    run_at: datetime
    original_text: str
    # True when the resolved command is dangerous=True and the user already
    # gave a spoken confirmation at schedule time — the runner then fires it
    # through CommandDispatcher.dispatch_preconfirmed, since there is nobody
    # to answer a confirmation prompt when the timer elapses.
    pre_confirmed: bool = False
    status: DelayedCommandStatus = DelayedCommandStatus.PENDING
    id: int | None = None
    created_at: datetime | None = None

    def is_due(self, now: datetime) -> bool:
        return self.status is DelayedCommandStatus.PENDING and now >= self.run_at
