from __future__ import annotations

import io
import zipfile
from dataclasses import replace

import pytest

from modules.integrations import packager


@pytest.fixture
def wordpress_dir(tmp_path, monkeypatch):
    directory = tmp_path / "wordpress-plugin"
    (directory / "assets").mkdir(parents=True)
    (directory / "jarvis-bridge.php").write_text(
        "<?php\n"
        "$url = get_option(JARVIS_OPTION_BACKEND_URL, '');\n"
        "$token = get_option(JARVIS_OPTION_API_TOKEN, '');\n",
        encoding="utf-8",
    )
    (directory / "assets" / "upload.js").write_text("// upload.js", encoding="utf-8")
    monkeypatch.setattr(packager, "_WORDPRESS_DIR", directory)
    return directory


@pytest.fixture
def figma_dir(tmp_path, monkeypatch):
    directory = tmp_path / "figma_plugin"
    directory.mkdir()
    (directory / "manifest.json").write_text('{"name": "test"}', encoding="utf-8")
    (directory / "ui.html").write_text(
        'const WS_TOKEN = "REPLACE_WITH_YOUR_ASSISTANT_API_TOKEN";', encoding="utf-8"
    )
    (directory / "code.js").write_text("// already built", encoding="utf-8")
    monkeypatch.setattr(packager, "_FIGMA_DIR", directory)
    return directory


@pytest.fixture
def blender_dir(tmp_path, monkeypatch):
    directory = tmp_path / "blender_addon"
    directory.mkdir()
    (directory / "__init__.py").write_text("bl_info = {}", encoding="utf-8")
    (directory / "server.py").write_text("# server", encoding="utf-8")
    (directory / "__pycache__").mkdir()
    (directory / "__pycache__" / "server.cpython-312.pyc").write_bytes(b"\x00")
    monkeypatch.setattr(packager, "_BLENDER_DIR", directory)
    return directory


@pytest.fixture(autouse=True)
def _fixed_backend_address(monkeypatch):
    monkeypatch.setattr(packager, "detect_lan_ip", lambda: "192.168.1.50")
    monkeypatch.setattr(packager, "settings", replace(packager.settings, api_token="test-token-123", port=8756))


def test_build_wordpress_plugin_zip_bakes_in_the_address_and_token(wordpress_dir) -> None:
    data = packager.build_wordpress_plugin_zip()

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        php = archive.read("wordpress-plugin/jarvis-bridge.php").decode("utf-8")
        assert archive.read("wordpress-plugin/assets/upload.js").decode("utf-8") == "// upload.js"

    assert "get_option(JARVIS_OPTION_BACKEND_URL, 'http://192.168.1.50:8756')" in php
    assert "get_option(JARVIS_OPTION_API_TOKEN, 'test-token-123')" in php


def test_build_figma_plugin_zip_bakes_in_the_token_and_uses_existing_code_js(figma_dir) -> None:
    data = packager.build_figma_plugin_zip()

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        ui_html = archive.read("figma_plugin/ui.html").decode("utf-8")
        code_js = archive.read("figma_plugin/code.js").decode("utf-8")
        archive.read("figma_plugin/manifest.json")  # present, doesn't raise

    assert 'const WS_TOKEN = "test-token-123";' in ui_html
    assert code_js == "// already built"


def test_build_figma_plugin_zip_raises_a_clear_error_when_npm_is_unavailable(tmp_path, monkeypatch) -> None:
    directory = tmp_path / "figma_plugin"
    directory.mkdir()
    (directory / "manifest.json").write_text("{}", encoding="utf-8")
    (directory / "ui.html").write_text("REPLACE_WITH_YOUR_ASSISTANT_API_TOKEN", encoding="utf-8")
    monkeypatch.setattr(packager, "_FIGMA_DIR", directory)
    monkeypatch.setattr(packager.shutil, "which", lambda _name: None)

    with pytest.raises(RuntimeError, match="npm"):
        packager.build_figma_plugin_zip()


def test_build_blender_addon_zip_wraps_the_py_files_in_one_folder_and_skips_pycache(blender_dir) -> None:
    data = packager.build_blender_addon_zip()

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())

    assert names == {"jarvis_voice_control/__init__.py", "jarvis_voice_control/server.py"}
