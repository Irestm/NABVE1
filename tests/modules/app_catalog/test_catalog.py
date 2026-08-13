from __future__ import annotations

import pytest

import modules.app_catalog.catalog as catalog
from modules.app_catalog.domain import InstalledApp


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    catalog._cache = None
    catalog._cached_at = 0.0


def test_caches_result_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(catalog, "_scan", lambda: calls.append(1) or [InstalledApp("A", "a", "desktop")])

    first = catalog.list_installed_apps()
    second = catalog.list_installed_apps()

    assert first == second
    assert len(calls) == 1


def test_force_refresh_bypasses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(catalog, "_scan", lambda: calls.append(1) or [])

    catalog.list_installed_apps()
    catalog.list_installed_apps(force_refresh=True)

    assert len(calls) == 2


def test_expired_cache_triggers_rescan(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(catalog, "_scan", lambda: calls.append(1) or [])
    monkeypatch.setattr(catalog, "_CACHE_TTL_SECONDS", 0.0)

    catalog.list_installed_apps()
    catalog.list_installed_apps()

    assert len(calls) == 2


def test_scan_exception_degrades_to_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Linux")

    def _raise() -> list[InstalledApp]:
        raise RuntimeError("boom")

    monkeypatch.setattr("modules.app_catalog.linux.list_installed_apps", _raise)

    assert catalog.list_installed_apps() == []


def test_unsupported_os_returns_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Darwin")

    assert catalog.list_installed_apps() == []
