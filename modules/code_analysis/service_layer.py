from __future__ import annotations

import asyncio
import base64
import io
import re
from pathlib import Path

import httpx

from core.ai_adapter_chain import candidate_chain
from core.logger import get_logger
from core.os_adapter import get_os_adapter
from core.os_adapter.screenshot import capture_window
from core.secret_store import get_secret
from modules.ai_bridge.api_providers import GEMINI_API_KEY_SECRET_NAME

logger = get_logger(__name__)

# A general-purpose text+vision model — distinct from
# modules/image_generation's gemini-3.1-flash-image-preview, which only
# generates images, not analyzes them.
_GEMINI_VISION_MODEL = "gemini-2.5-flash"
_GEMINI_API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_REQUEST_TIMEOUT_SECONDS = 30.0

_GITHUB_BLOB_PATTERN = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$")

GITHUB_PAT_SECRET_NAME = "github_pat"

# Confirmed by hand that Linux PyCharm's WM_CLASS starts with "jetbrains-"
# followed by the product name; matching just "pycharm" as a substring
# covers both that and any older/differently-cased variant without
# depending on the exact prefix.
_PYCHARM_WM_CLASS_MARKER = "pycharm"
# Best-effort: PyCharm's window title only shows a full absolute path when
# the window is wide enough and certain settings are on — not guaranteed.
# When this finds nothing, analyze_active_editor falls back to the
# screenshot+vision path below instead of failing outright.
_ABSOLUTE_PATH_PATTERN = re.compile(r"(/[^\s:]+\.[A-Za-z0-9]+)")


class CodeAnalysisError(RuntimeError):
    pass


def _build_prompt(code: str, instruction: str) -> str:
    return f'Вот код:\n"""{code}"""\n\nЗадача: {instruction}\n\nОтветь по существу, на русском, если не попросили иначе.'


async def analyze_code(code: str, instruction: str) -> str:
    """Tries candidate_chain(instruction)'s adapters in order, same
    all-or-nothing shape as modules.text_editing.service_layer.edit_text."""
    prompt = _build_prompt(code, instruction)
    last_error: Exception | None = None
    for adapter in candidate_chain(instruction):
        try:
            result = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            last_error = exc
            logger.warning("Code-analysis adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue
        stripped = result.strip()
        if stripped:
            return stripped
    logger.error("All AI adapters failed to analyze code: %s", last_error, exc_info=last_error)
    raise CodeAnalysisError("Не удалось проанализировать код — все AI-адаптеры недоступны.")


async def fetch_github_file(url: str) -> str:
    match = _GITHUB_BLOB_PATTERN.match(url.strip())
    if not match:
        raise CodeAnalysisError(
            "Это не похоже на ссылку на файл GitHub "
            "(нужен вид https://github.com/владелец/репозиторий/blob/ветка/путь)."
        )
    owner, repo, branch, path = match.groups()
    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
    headers = {}
    pat = get_secret(GITHUB_PAT_SECRET_NAME)
    if pat:
        # raw.githubusercontent.com honors the same token auth as the REST
        # API for private-repo access — public repos work identically with
        # or without it, so this is always safe to attach when configured.
        headers["Authorization"] = f"token {pat}"
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.get(raw_url, headers=headers)
    if response.status_code == 404:
        raise CodeAnalysisError(
            "Файл не найден на GitHub — если репозиторий приватный, добавьте свой токен "
            "в Настройках → Интеграции."
        )
    if response.status_code >= 400:
        raise CodeAnalysisError(f"Не удалось скачать файл с GitHub: {response.status_code}.")
    return response.text


def _find_open_file_from_title(title: str) -> Path | None:
    for match in _ABSOLUTE_PATH_PATTERN.finditer(title):
        candidate = Path(match.group(1))
        if candidate.is_file():
            return candidate
    return None


async def _capture_screenshot_png() -> bytes:
    adapter = get_os_adapter()
    active = await asyncio.to_thread(adapter.get_active_window)
    if active is None:
        raise CodeAnalysisError("Не удалось определить активное окно.")
    image, _offset = await asyncio.to_thread(capture_window, active)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def _analyze_image(image_bytes: bytes, instruction: str) -> str:
    api_key = get_secret(GEMINI_API_KEY_SECRET_NAME)
    if not api_key:
        raise CodeAnalysisError(
            "Анализ по скриншоту требует настроенного Gemini-ключа (Настройки → Интеграции)."
        )
    encoded = base64.b64encode(image_bytes).decode("ascii")
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(
            _GEMINI_API_URL_TEMPLATE.format(model=_GEMINI_VISION_MODEL),
            params={"key": api_key},
            json={
                "contents": [
                    {
                        "parts": [
                            {"text": instruction},
                            {"inline_data": {"mime_type": "image/png", "data": encoded}},
                        ]
                    }
                ]
            },
        )
    if response.status_code >= 400:
        raise CodeAnalysisError(f"Gemini отказал в анализе скриншота: {response.text}")
    payload = response.json()
    candidates = payload.get("candidates") or []
    if not candidates:
        raise CodeAnalysisError("Gemini не вернул ответ по скриншоту.")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts).strip()
    if not text:
        raise CodeAnalysisError("Gemini вернул пустой ответ по скриншоту.")
    return text


async def analyze_active_editor(instruction: str) -> str:
    """Combines both approaches discussed for "IDE open" analysis: if the
    active window is PyCharm and its title happens to expose a real,
    existing absolute file path, that file is read directly (exact syntax,
    not a vision guess) and analyzed as text through analyze_code().
    Otherwise — a different editor, or PyCharm without a resolvable path in
    its title (not guaranteed, varies by settings/window width) — falls
    back to a screenshot + Gemini vision call, universal across editors but
    requires a configured Gemini key and can't see anything scrolled
    off-screen."""
    adapter = get_os_adapter()
    active = await asyncio.to_thread(adapter.get_active_window)
    if active is None:
        raise CodeAnalysisError("Не удалось определить активное окно.")

    is_pycharm = active.wm_class is not None and _PYCHARM_WM_CLASS_MARKER in active.wm_class.lower()
    if is_pycharm:
        file_path = _find_open_file_from_title(active.title)
        if file_path is not None:
            try:
                code = file_path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning("Could not read detected PyCharm file %s: %s", file_path, exc)
            else:
                return await analyze_code(code, instruction)

    screenshot = await _capture_screenshot_png()
    return await _analyze_image(screenshot, instruction)
