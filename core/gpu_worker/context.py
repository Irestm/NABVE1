from __future__ import annotations

import threading
from typing import Any, Callable, Hashable, TypeVar

T = TypeVar("T")


class WorkerContext:
    def __init__(self, gpu_allowed: bool) -> None:
        self.gpu_allowed = gpu_allowed
        self._values: dict[Hashable, Any] = {}
        self._locks: dict[Hashable, threading.Lock] = {}
        self._guard = threading.Lock()

    def cached(self, key: Hashable, factory: Callable[[], T]) -> T:
        with self._guard:
            if key in self._values:
                return self._values[key]
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            with self._guard:
                if key in self._values:
                    return self._values[key]
            value = factory()
            with self._guard:
                self._values[key] = value
            return value
