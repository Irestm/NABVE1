from __future__ import annotations

from pathlib import Path

from modules.app_catalog import windows as app_windows
from modules.app_catalog.domain import InstalledApp


def _touch_lnk(directory: Path, name: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.lnk").write_bytes(b"")


def test_list_shortcut_apps_finds_lnk_files_recursively(tmp_path: Path) -> None:
    start_menu = tmp_path / "Start Menu" / "Programs"
    _touch_lnk(start_menu, "Notepad")
    _touch_lnk(start_menu / "Accessories", "Calculator")

    apps = app_windows.list_shortcut_apps((start_menu,))

    names = {app.display_name for app in apps}
    assert names == {"Notepad", "Calculator"}
    assert all(app.source == "shortcut" for app in apps)


def test_list_shortcut_apps_deduplicates_by_display_name_across_directories(tmp_path: Path) -> None:
    common = tmp_path / "common"
    user = tmp_path / "user"
    _touch_lnk(common, "Notepad")
    _touch_lnk(user, "Notepad")

    apps = app_windows.list_shortcut_apps((common, user))

    assert len(apps) == 1


def test_list_shortcut_apps_skips_missing_directories(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"

    assert app_windows.list_shortcut_apps((missing,)) == []


def test_list_shortcut_apps_ignores_non_lnk_files(tmp_path: Path) -> None:
    start_menu = tmp_path / "Start Menu"
    start_menu.mkdir()
    (start_menu / "readme.txt").write_text("not a shortcut")

    assert app_windows.list_shortcut_apps((start_menu,)) == []


def test_steam_root_from_registry_returns_none_without_winreg() -> None:
    # This test runs on Linux, where `import winreg` genuinely fails —
    # exercising the same ImportError early-return real Windows-without-Steam
    # machines would never hit, but Linux dev/CI boxes always do.
    assert app_windows._steam_root_from_registry() is None


def test_list_installed_apps_combines_shortcuts_and_steam_games(tmp_path: Path, monkeypatch) -> None:
    start_menu = tmp_path / "Start Menu"
    _touch_lnk(start_menu, "Notepad")
    steam_root = tmp_path / "steam"
    steam_root.mkdir()

    steam_game = InstalledApp(display_name="Half-Life", launch_target="steam://rungameid/70", source="steam")
    monkeypatch.setattr(app_windows, "list_steam_games", lambda root: [steam_game])

    apps = app_windows.list_installed_apps((start_menu,), steam_root=steam_root)

    assert {app.display_name for app in apps} == {"Notepad", "Half-Life"}


def test_list_installed_apps_skips_steam_when_root_is_not_a_directory(tmp_path: Path, monkeypatch) -> None:
    start_menu = tmp_path / "Start Menu"
    _touch_lnk(start_menu, "Notepad")

    def _fail(*_args: object) -> list[InstalledApp]:
        raise AssertionError("list_steam_games should not be called without a valid steam_root")

    monkeypatch.setattr(app_windows, "list_steam_games", _fail)

    apps = app_windows.list_installed_apps((start_menu,), steam_root=tmp_path / "does-not-exist")

    assert [app.display_name for app in apps] == ["Notepad"]


def test_list_installed_apps_falls_back_to_registry_lookup_when_steam_root_not_given(
    tmp_path: Path, monkeypatch
) -> None:
    start_menu = tmp_path / "Start Menu"
    _touch_lnk(start_menu, "Notepad")
    monkeypatch.setattr(app_windows, "_steam_root_from_registry", lambda: None)

    apps = app_windows.list_installed_apps((start_menu,))

    assert [app.display_name for app in apps] == ["Notepad"]
