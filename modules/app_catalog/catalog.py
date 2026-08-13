from __future__ import annotations

import platform
import threading
import time

from core.logger import get_logger
from modules.app_catalog.domain import InstalledApp

logger = get_logger(__name__)

# Scanning .desktop files / Start Menu shortcuts / Steam manifests touches
# disk (a handful of directory listings plus small text files) — cheap, but
# not free enough to redo on every single "open X" request. Not persisted
# across restarts: a newly installed app just waits out one cache period,
# an acceptable trade-off for a query that only exists to resolve a spoken
# app/game name.
_CACHE_TTL_SECONDS = 300.0

_lock = threading.Lock()
_cache: list[InstalledApp] | None = None
_cached_at = 0.0


def _scan() -> list[InstalledApp]:
    system = platform.system()
    if system == "Linux":
        from modules.app_catalog.linux import list_installed_apps as scan
    elif system == "Windows":
        from modules.app_catalog.windows import list_installed_apps as scan
    else:
        logger.info(
            "No app catalog scanner for OS '%s'; open_app resolution will have no local candidates", system
        )
        return []

    try:
        return scan()
    except Exception:
        # Never let a scanning bug take down whatever's asking for the
        # catalog — same fallback philosophy as
        # modules.hardware_adaptive.hardware_detector's detection failures.
        logger.warning("Failed to scan installed applications", exc_info=True)
        return []


def list_installed_apps(*, force_refresh: bool = False) -> list[InstalledApp]:
    """All installed apps/games this process could find on the local
    machine (see modules/app_catalog/{linux,windows}.py), cached for
    _CACHE_TTL_SECONDS. `force_refresh=True` bypasses the cache — useful
    right after installing something new, not needed for normal use."""
    global _cache, _cached_at
    with _lock:
        now = time.monotonic()
        if not force_refresh and _cache is not None and (now - _cached_at) < _CACHE_TTL_SECONDS:
            return _cache
        _cache = _scan()
        _cached_at = now
        logger.info("App catalog scan found %d installed application(s)", len(_cache))
        return _cache
