from __future__ import annotations

import pytest

from modules.software_installer import package_map


@pytest.mark.parametrize(
    "spoken,expected",
    [
        ("VLC", "vlc"),
        ("вэ эл си", "vlc"),
        ("влц", "vlc"),
        ("гугл хром", "chrome"),
        ("vs code", "vscode"),
        ("телеграм", "telegram"),
        ("Telegram Desktop", "telegram"),
        ("7 zip", "7zip"),
        ("winrar", "7zip"),
        ("obs studio", "obs"),
    ],
)
def test_resolve_known_names_and_aliases(spoken: str, expected: str) -> None:
    assert package_map.resolve(spoken) == expected


@pytest.mark.parametrize("spoken", ["будильник", "какая-то неведомая программа", "", "   "])
def test_resolve_unknown_returns_none(spoken: str) -> None:
    assert package_map.resolve(spoken) is None


def test_package_ids_shape() -> None:
    ids = package_map.package_ids("vlc")
    assert ids["apt"] == "vlc"
    assert ids["winget"] == "VideoLAN.VLC"
    assert set(ids) >= {"apt", "dnf", "pacman", "flatpak", "snap", "winget"}
