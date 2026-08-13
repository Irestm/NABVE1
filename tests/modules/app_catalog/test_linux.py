from __future__ import annotations

import os
import stat
from pathlib import Path

from modules.app_catalog.linux import (
    _parse_desktop_entry,
    _resolve_flatpak_launch,
    list_appimage_apps,
    list_desktop_apps,
    list_installed_apps,
    list_path_executables,
)


def _write_desktop_entry(path: Path, *, name: str, exec_line: str, extra: str = "") -> None:
    path.write_text(
        f"""[Desktop Entry]
Type=Application
Name={name}
Exec={exec_line}
{extra}
""",
        encoding="utf-8",
    )


def test_parses_name_and_strips_field_codes(tmp_path: Path) -> None:
    entry = tmp_path / "app.desktop"
    _write_desktop_entry(entry, name="OBS Studio", exec_line="obs %U")

    app = _parse_desktop_entry(entry)

    assert app is not None
    assert app.display_name == "OBS Studio"
    assert app.launch_target == "obs"
    assert app.source == "desktop"


def test_handles_quoted_paths_with_spaces(tmp_path: Path) -> None:
    entry = tmp_path / "app.desktop"
    _write_desktop_entry(entry, name="My App", exec_line='"/opt/my app/bin/run" %f')

    app = _parse_desktop_entry(entry)

    assert app is not None
    assert app.launch_target == "/opt/my app/bin/run"


def test_no_display_entries_are_excluded(tmp_path: Path) -> None:
    entry = tmp_path / "hidden.desktop"
    _write_desktop_entry(entry, name="Hidden Helper", exec_line="helper", extra="NoDisplay=true")

    assert _parse_desktop_entry(entry) is None


def test_hidden_entries_are_excluded(tmp_path: Path) -> None:
    entry = tmp_path / "hidden.desktop"
    _write_desktop_entry(entry, name="Removed App", exec_line="removed", extra="Hidden=true")

    assert _parse_desktop_entry(entry) is None


def test_missing_exec_is_excluded(tmp_path: Path) -> None:
    entry = tmp_path / "no-exec.desktop"
    entry.write_text("[Desktop Entry]\nType=Application\nName=No Exec\n", encoding="utf-8")

    assert _parse_desktop_entry(entry) is None


def test_list_desktop_apps_deduplicates_by_name(tmp_path: Path) -> None:
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    _write_desktop_entry(dir_a / "app.desktop", name="Same App", exec_line="app-a")
    _write_desktop_entry(dir_b / "app.desktop", name="Same App", exec_line="app-b")

    apps = list_desktop_apps([dir_a, dir_b])

    assert len(apps) == 1


def test_list_desktop_apps_ignores_nonexistent_dirs(tmp_path: Path) -> None:
    assert list_desktop_apps([tmp_path / "does-not-exist"]) == []


def test_list_installed_apps_skips_missing_steam_root(tmp_path: Path) -> None:
    apps_dir = tmp_path / "applications"
    apps_dir.mkdir()
    _write_desktop_entry(apps_dir / "app.desktop", name="Some App", exec_line="some-app")

    # appimage_dirs/path_directories explicitly emptied - otherwise this
    # would pick up whatever AppImages/PATH executables happen to exist on
    # the machine actually running the test.
    apps = list_installed_apps(
        desktop_dirs=[apps_dir],
        steam_roots=[tmp_path / "no-steam-here"],
        appimage_dirs=[],
        path_directories=[],
    )

    assert len(apps) == 1
    assert apps[0].display_name == "Some App"


# --- _resolve_flatpak_launch ------------------------------------------------


def test_resolve_flatpak_launch_finds_the_app_id() -> None:
    tokens = ["/usr/bin/flatpak", "run", "--branch=stable", "--arch=x86_64", "--command=telegram-desktop", "org.telegram.desktop"]
    assert _resolve_flatpak_launch(tokens) == "flatpak run org.telegram.desktop"


def test_resolve_flatpak_launch_ignores_field_code_tokens() -> None:
    tokens = ["flatpak", "run", "org.telegram.desktop", "@@u", "%u", "@@"]
    assert _resolve_flatpak_launch(tokens) == "flatpak run org.telegram.desktop"


def test_resolve_flatpak_launch_returns_none_for_non_flatpak_exec() -> None:
    assert _resolve_flatpak_launch(["obs", "%U"]) is None


def test_resolve_flatpak_launch_returns_none_for_empty_tokens() -> None:
    assert _resolve_flatpak_launch([]) is None


def test_desktop_entry_with_flatpak_exec_resolves_to_flatpak_run(tmp_path: Path) -> None:
    entry = tmp_path / "org.telegram.desktop.desktop"
    _write_desktop_entry(
        entry,
        name="Telegram",
        exec_line="/usr/bin/flatpak run --branch=stable --arch=x86_64 --command=telegram-desktop org.telegram.desktop @@u %u @@",
    )

    app = _parse_desktop_entry(entry)

    assert app is not None
    assert app.launch_target == "flatpak run org.telegram.desktop"


# --- list_appimage_apps ------------------------------------------------------


def test_list_appimage_apps_finds_executable_appimages(tmp_path: Path) -> None:
    appimage = tmp_path / "MyTool-1.2.3.AppImage"
    appimage.write_text("fake binary", encoding="utf-8")
    appimage.chmod(appimage.stat().st_mode | stat.S_IEXEC)

    apps = list_appimage_apps([tmp_path])

    assert len(apps) == 1
    assert apps[0].display_name == "MyTool-1.2.3"
    assert apps[0].launch_target == str(appimage)
    assert apps[0].source == "appimage"


def test_list_appimage_apps_skips_non_executable_files(tmp_path: Path) -> None:
    appimage = tmp_path / "NotExecutable.AppImage"
    appimage.write_text("fake binary", encoding="utf-8")
    appimage.chmod(appimage.stat().st_mode & ~stat.S_IEXEC & ~stat.S_IXGRP & ~stat.S_IXOTH)

    assert list_appimage_apps([tmp_path]) == []


def test_list_appimage_apps_ignores_nonexistent_dirs(tmp_path: Path) -> None:
    assert list_appimage_apps([tmp_path / "does-not-exist"]) == []


# --- list_path_executables ---------------------------------------------------


def test_list_path_executables_finds_executables_in_given_dirs(tmp_path: Path) -> None:
    binary = tmp_path / "my-custom-tool"
    binary.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "not-executable.txt").write_text("data", encoding="utf-8")

    apps = list_path_executables([tmp_path])

    assert len(apps) == 1
    assert apps[0].display_name == "my-custom-tool"
    assert apps[0].launch_target == "my-custom-tool"
    assert apps[0].source == "path"


def test_list_path_executables_dedupes_across_directories(tmp_path: Path) -> None:
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    for directory in (dir_a, dir_b):
        binary = directory / "python3"
        binary.write_text("", encoding="utf-8")
        binary.chmod(binary.stat().st_mode | stat.S_IEXEC)

    apps = list_path_executables([dir_a, dir_b])

    assert len(apps) == 1


def test_list_path_executables_ignores_nonexistent_dirs() -> None:
    assert list_path_executables([Path("/does/not/exist")]) == []


def test_list_path_executables_defaults_to_real_path_env(monkeypatch, tmp_path: Path) -> None:
    binary = tmp_path / "real-path-tool"
    binary.write_text("", encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(os, "environ", {**os.environ, "PATH": str(tmp_path)})

    apps = list_path_executables()

    assert any(app.display_name == "real-path-tool" for app in apps)
