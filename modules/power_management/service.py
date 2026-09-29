from __future__ import annotations

import os
import threading
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

from core.config import DATA_DIR
from core.logger import get_logger
from modules.power_management.domain import PowerPolicy, PowerSnapshot, compute_policy
from modules.power_management.settings_store import SETTINGS_FILE_NAME, PowerSettingsStore

logger = get_logger(__name__)

ON_BATTERY_ENV = "ASSISTANT_ON_BATTERY"

PolicyListener = Callable[[PowerPolicy], None]


@dataclass(frozen=True)
class WorkerStatus:
    running: bool
    device: str | None


WorkerStatusProvider = Callable[[], WorkerStatus]


def on_battery_from_env() -> bool:
    return os.environ.get(ON_BATTERY_ENV, "").strip().lower() in ("1", "true", "yes")


def _no_worker() -> WorkerStatus:
    return WorkerStatus(running=False, device=None)


class PowerService:
    def __init__(self, store: PowerSettingsStore, on_battery: bool = False) -> None:
        self._store = store
        self._lock = threading.Lock()
        self._settings = store.load()
        self._on_battery = on_battery
        self._listeners: list[PolicyListener] = []
        self._worker_status: WorkerStatusProvider = _no_worker

    def snapshot(self) -> PowerSnapshot:
        with self._lock:
            return self._snapshot_locked()

    def policy(self) -> PowerPolicy:
        return self.snapshot().policy

    def worker_status(self) -> WorkerStatus:
        return self._worker_status()

    def bind_worker_status(self, provider: WorkerStatusProvider) -> None:
        self._worker_status = provider

    def set_on_battery(self, on_battery: bool) -> PowerSnapshot:
        with self._lock:
            before = self._snapshot_locked().policy
            self._on_battery = on_battery
            after = self._snapshot_locked()
        logger.info("Power source changed: on_battery=%s", on_battery)
        self._notify_if_changed(before, after.policy)
        return after

    def update_settings(self, changes: Mapping[str, Any]) -> PowerSnapshot:
        with self._lock:
            before = self._snapshot_locked().policy
            updated = replace(self._settings, **dict(changes))
            if updated != self._settings:
                self._store.save(updated)
                self._settings = updated
            after = self._snapshot_locked()
        self._notify_if_changed(before, after.policy)
        return after

    def subscribe(self, listener: PolicyListener) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def _snapshot_locked(self) -> PowerSnapshot:
        return PowerSnapshot(
            on_battery=self._on_battery,
            settings=self._settings,
            policy=compute_policy(self._settings, self._on_battery),
        )

    def _notify_if_changed(self, before: PowerPolicy, after: PowerPolicy) -> None:
        if before == after:
            return
        with self._lock:
            listeners = list(self._listeners)
            current = self._snapshot_locked().policy
        for listener in listeners:
            try:
                listener(current)
            except Exception:
                logger.exception("Power policy listener failed")


_service: PowerService | None = None
_service_lock = threading.Lock()


def get_power_service() -> PowerService:
    global _service
    with _service_lock:
        if _service is None:
            _service = PowerService(PowerSettingsStore(DATA_DIR / SETTINGS_FILE_NAME), on_battery_from_env())
        return _service
