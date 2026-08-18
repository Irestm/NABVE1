from __future__ import annotations

import io
import shutil
import subprocess
import zipfile
from pathlib import Path

from core.config import BASE_DIR, detect_lan_ip, settings
from core.logger import get_logger

logger = get_logger(__name__)

_WORDPRESS_DIR = BASE_DIR / "wordpress-plugin"
_FIGMA_DIR = BASE_DIR / "figma_plugin"
_BLENDER_DIR = BASE_DIR / "blender_addon"


def _backend_url() -> str:
    # Same address the LAN-pairing QR code uses (see core/main.py's
    # /api/lan_url) — the one address every other client of this backend
    # already reaches it at, so it's the right default to bake into a
    # downloaded plugin too.
    return f"http://{detect_lan_ip()}:{settings.port}"


def build_wordpress_plugin_zip() -> bytes:
    """Zips wordpress-plugin/ with the backend URL and API token already
    filled in as the settings screen's defaults (see jarvis-bridge.php's own
    get_option(..., '') calls) — the admin just activates the plugin and
    starts uploading, no manual address/token entry. Still overridable from
    the plugin's own WordPress settings screen if the LAN address changes."""
    php_source = (_WORDPRESS_DIR / "jarvis-bridge.php").read_text(encoding="utf-8")
    backend_url = _backend_url()
    token = settings.api_token
    patched = php_source.replace(
        "get_option(JARVIS_OPTION_BACKEND_URL, '')", f"get_option(JARVIS_OPTION_BACKEND_URL, '{backend_url}')"
    ).replace("get_option(JARVIS_OPTION_API_TOKEN, '')", f"get_option(JARVIS_OPTION_API_TOKEN, '{token}')")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("wordpress-plugin/jarvis-bridge.php", patched)
        upload_js = _WORDPRESS_DIR / "assets" / "upload.js"
        archive.writestr("wordpress-plugin/assets/upload.js", upload_js.read_text(encoding="utf-8"))
    return buffer.getvalue()


def _ensure_figma_code_js() -> Path:
    """figma_plugin/code.js is a gitignored build artifact (see .gitignore's
    own comment — historically rebuilt locally by whoever's developing the
    plugin, via `npm run build`). This download endpoint is for a non-
    technical end user instead, who has neither Node nor a reason to run
    that themselves — build it here, once, the first time it's needed."""
    code_js = _FIGMA_DIR / "code.js"
    if code_js.is_file():
        return code_js

    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError(
            "Не удалось собрать плагин Figma — на этом компьютере не найден npm. "
            "Установите Node.js или соберите плагин вручную (см. figma_plugin/README.md)."
        )
    subprocess.run([npm, "install"], cwd=_FIGMA_DIR, capture_output=True, text=True, check=True)
    result = subprocess.run([npm, "run", "build"], cwd=_FIGMA_DIR, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not code_js.is_file():
        logger.error("figma_plugin build failed: %s", result.stderr.strip() or result.stdout.strip())
        raise RuntimeError("Не удалось собрать плагин Figma — подробности в логе бэкенда.")
    return code_js


def build_figma_plugin_zip() -> bytes:
    """Zips figma_plugin/ with WS_TOKEN already filled in (ui.html's own
    placeholder) and code.js already built — "Import plugin from manifest…"
    is then the only manual step left, matching Blender/WordPress."""
    code_js = _ensure_figma_code_js()
    ui_html = (_FIGMA_DIR / "ui.html").read_text(encoding="utf-8")
    patched_ui = ui_html.replace('"REPLACE_WITH_YOUR_ASSISTANT_API_TOKEN"', f'"{settings.api_token}"')

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("figma_plugin/manifest.json", (_FIGMA_DIR / "manifest.json").read_text(encoding="utf-8"))
        archive.writestr("figma_plugin/ui.html", patched_ui)
        archive.writestr("figma_plugin/code.js", code_js.read_text(encoding="utf-8"))
    return buffer.getvalue()


def build_blender_addon_zip() -> bytes:
    """Zips blender_addon/ as a single top-level folder (Blender's own
    Install… expects that shape, not loose files) — the "заархивируйте её
    в .zip сами" step IntegrationsPanel used to ask of the user."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(_BLENDER_DIR.glob("*.py")):
            archive.writestr(f"jarvis_voice_control/{path.name}", path.read_text(encoding="utf-8"))
    return buffer.getvalue()
