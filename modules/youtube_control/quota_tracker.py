from __future__ import annotations

from datetime import date

from core.config import DATA_DIR
from modules.ai_bridge.state_store import StateStore
from modules.youtube_control.domain import QuotaStatus

DAILY_UNIT_LIMIT = 10_000
SEARCH_COST_UNITS = 100
WARNING_THRESHOLD_RATIO = 0.8

_DB_PATH = DATA_DIR / "youtube_control" / "state.db"
_UNITS_USED_KEY = "units_used"
_LAST_RESET_DATE_KEY = "last_reset_date"
_WARNED_KEY = "warned_near_limit"


class QuotaTracker:
    def __init__(self, store: StateStore | None = None) -> None:
        self._store = store or StateStore(db_path=_DB_PATH)

    def _maybe_reset(self) -> None:
        today = date.today().isoformat()
        if self._store.get(_LAST_RESET_DATE_KEY) != today:
            self._store.set(_LAST_RESET_DATE_KEY, today)
            self._store.set(_UNITS_USED_KEY, "0")
            self._store.set(_WARNED_KEY, "0")

    def units_used(self) -> int:
        self._maybe_reset()
        return int(self._store.get(_UNITS_USED_KEY) or "0")

    def record_usage(self, units: int) -> None:
        self._maybe_reset()
        self._store.set(_UNITS_USED_KEY, str(self.units_used() + units))

    def status(self) -> QuotaStatus:
        used = self.units_used()
        remaining_units = max(DAILY_UNIT_LIMIT - used, 0)
        return QuotaStatus(
            units_used=used,
            daily_limit=DAILY_UNIT_LIMIT,
            remaining_searches=remaining_units // SEARCH_COST_UNITS,
            near_limit=used >= DAILY_UNIT_LIMIT * WARNING_THRESHOLD_RATIO,
            exhausted=used >= DAILY_UNIT_LIMIT,
        )

    def consume_near_limit_warning(self) -> bool:
        self._maybe_reset()
        if not self.status().near_limit:
            return False
        if self._store.get(_WARNED_KEY) == "1":
            return False
        self._store.set(_WARNED_KEY, "1")
        return True
