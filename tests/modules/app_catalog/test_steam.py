from __future__ import annotations

from pathlib import Path

from modules.app_catalog.steam import list_steam_games


def _write_manifest(steamapps_dir: Path, appid: str, name: str) -> None:
    steamapps_dir.mkdir(parents=True, exist_ok=True)
    (steamapps_dir / f"appmanifest_{appid}.acf").write_text(
        f"""
        "AppState"
        {{
            "appid"		"{appid}"
            "Universe"		"1"
            "name"		"{name}"
            "StateFlags"		"4"
        }}
        """,
        encoding="utf-8",
    )


def test_finds_games_in_main_library(tmp_path: Path) -> None:
    steam_root = tmp_path / "steam"
    _write_manifest(steam_root / "steamapps", "588650", "Dead Cells")

    apps = list_steam_games(steam_root)

    assert len(apps) == 1
    assert apps[0].display_name == "Dead Cells"
    assert apps[0].launch_target == "steam://rungameid/588650"
    assert apps[0].source == "steam"


def test_follows_additional_libraries_from_libraryfolders_vdf(tmp_path: Path) -> None:
    steam_root = tmp_path / "steam"
    extra_library = tmp_path / "external_drive" / "SteamLibrary"
    (steam_root / "steamapps").mkdir(parents=True)
    (steam_root / "steamapps" / "libraryfolders.vdf").write_text(
        f"""
        "libraryfolders"
        {{
            "0"
            {{
                "path"		"{steam_root}"
            }}
            "1"
            {{
                "path"		"{extra_library}"
            }}
        }}
        """,
        encoding="utf-8",
    )
    _write_manifest(extra_library / "steamapps", "413150", "Stardew Valley")

    apps = list_steam_games(steam_root)

    assert len(apps) == 1
    assert apps[0].display_name == "Stardew Valley"


def test_missing_steam_root_returns_empty_list(tmp_path: Path) -> None:
    assert list_steam_games(tmp_path / "does-not-exist") == []


def test_malformed_manifest_is_skipped_not_raised(tmp_path: Path) -> None:
    steamapps_dir = tmp_path / "steam" / "steamapps"
    steamapps_dir.mkdir(parents=True)
    (steamapps_dir / "appmanifest_1.acf").write_text('"AppState" { "appid" }', encoding="utf-8")

    assert list_steam_games(tmp_path / "steam") == []
