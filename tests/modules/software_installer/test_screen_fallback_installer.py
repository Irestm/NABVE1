from __future__ import annotations

import sys
import types

import pytest

import modules.software_installer.screen_fallback_installer as sfi
from core.os_adapter.base import ActiveWindow


class _FakeAdapter:
    def __init__(self, title: str) -> None:
        self._title = title

    def get_active_window(self):
        return ActiveWindow(title=self._title, pid=1, bbox=(0, 0, 800, 600))


def _wire(monkeypatch, *, title: str, found_template: str | None) -> list[tuple[int, int]]:
    clicks: list[tuple[int, int]] = []
    monkeypatch.setattr(sfi, "get_os_adapter", lambda: _FakeAdapter(title))
    monkeypatch.setattr(
        sfi,
        "_find_template",
        lambda name, confidence: (100, 200) if name == found_template else None,
    )
    fake_pyautogui = types.SimpleNamespace(click=lambda x, y: clicks.append((x, y)))
    monkeypatch.setitem(sys.modules, "pyautogui", fake_pyautogui)
    return clicks


def test_clicks_the_first_matching_template(monkeypatch) -> None:
    clicks = _wire(monkeypatch, title="Setup — VLC media player", found_template="next_ru.png")

    message = sfi.click_installer_button("next")

    assert clicks == [(100, 200)]
    assert "Далее" in message


def test_refuses_when_active_window_is_a_browser(monkeypatch) -> None:
    _wire(monkeypatch, title="VLC download — Mozilla Firefox", found_template="next_ru.png")

    with pytest.raises(sfi.UnsafeInstallerContextError):
        sfi.click_installer_button("next")


def test_raises_when_no_template_matches(monkeypatch) -> None:
    _wire(monkeypatch, title="Installer", found_template=None)

    with pytest.raises(sfi.InstallerButtonNotFoundError):
        sfi.click_installer_button("install")


def test_unknown_button_kind_raises_value_error(monkeypatch) -> None:
    _wire(monkeypatch, title="Installer", found_template=None)
    with pytest.raises(ValueError):
        sfi.click_installer_button("teleport")
