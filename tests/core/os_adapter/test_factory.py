from __future__ import annotations

import pytest

from core.os_adapter import factory
from core.os_adapter.linux import LinuxAdapter
from core.os_adapter.windows import WindowsAdapter


@pytest.fixture(autouse=True)
def _reset_cached_adapter():
    factory._adapter = None
    yield
    factory._adapter = None


def test_get_os_adapter_returns_linux_adapter_on_linux(monkeypatch) -> None:
    monkeypatch.setattr(factory.platform, "system", lambda: "Linux")

    adapter = factory.get_os_adapter()

    assert isinstance(adapter, LinuxAdapter)


def test_get_os_adapter_returns_windows_adapter_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(factory.platform, "system", lambda: "Windows")

    adapter = factory.get_os_adapter()

    assert isinstance(adapter, WindowsAdapter)


def test_get_os_adapter_raises_for_an_unsupported_platform(monkeypatch) -> None:
    monkeypatch.setattr(factory.platform, "system", lambda: "Plan9")

    with pytest.raises(RuntimeError, match="Plan9"):
        factory.get_os_adapter()


def test_get_os_adapter_caches_the_instance_across_calls(monkeypatch) -> None:
    monkeypatch.setattr(factory.platform, "system", lambda: "Linux")

    first = factory.get_os_adapter()
    second = factory.get_os_adapter()

    assert first is second
