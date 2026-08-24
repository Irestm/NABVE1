from __future__ import annotations

import base64

import httpx

from core.logger import get_logger
from core.secret_store import get_secret
from modules.ai_bridge.api_providers import GEMINI_API_KEY_SECRET_NAME

logger = get_logger(__name__)

# Same general-purpose text+vision model modules.code_analysis.service_layer
# uses for its screenshot analysis — distinct from modules.image_generation's
# gemini-3.1-flash-image-preview, which only generates images, not analyzes
# them. Not shared code with code_analysis (that module keeps its own
# private copy of this same call) — see modules.fitness_tracker's plan for
# why: extracting this shared helper here lets a new caller
# (modules.fitness_tracker.meal_analyzer) reuse the exact same call shape
# without touching code_analysis's already-tested implementation.
_GEMINI_VISION_MODEL = "gemini-2.5-flash"
_GEMINI_API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_REQUEST_TIMEOUT_SECONDS = 30.0


class VisionAnalysisError(RuntimeError):
    pass


async def analyze_image(image_bytes: bytes, instruction: str, *, mime_type: str = "image/png") -> str:
    """Sends `image_bytes` plus a text `instruction` to Gemini's vision-
    capable endpoint and returns its free-text answer. Requires a configured
    Gemini API key (core/secret_store.py); raises VisionAnalysisError for
    every failure mode (no key, HTTP error, empty/malformed response) so
    callers can catch one exception type regardless of what went wrong."""
    api_key = get_secret(GEMINI_API_KEY_SECRET_NAME)
    if not api_key:
        raise VisionAnalysisError("Анализ изображения требует настроенного Gemini-ключа (Настройки → Интеграции).")

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
                            {"inline_data": {"mime_type": mime_type, "data": encoded}},
                        ]
                    }
                ]
            },
        )
    if response.status_code >= 400:
        raise VisionAnalysisError(f"Gemini отказал в анализе изображения: {response.text}")

    payload = response.json()
    candidates = payload.get("candidates") or []
    if not candidates:
        raise VisionAnalysisError("Gemini не вернул ответ по изображению.")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts).strip()
    if not text:
        raise VisionAnalysisError("Gemini вернул пустой ответ по изображению.")
    return text
