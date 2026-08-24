from __future__ import annotations

import base64

import httpx

_GEMINI_API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Nano Banana 2 — the older Gemini 2.5 Flash Image (Nano Banana 1) is
# scheduled to shut down 2026-10-02, so this deliberately targets the
# current model, not the one used elsewhere in this codebase for text
# (modules/ai_bridge/api_providers.py's gemini-2.5-flash, unaffected by this
# specific shutdown). Swap here if Google renames/retires this one too —
# nothing else in this module hardcodes a model name.
_GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image-preview"
# Image generation takes noticeably longer than a text completion.
_REQUEST_TIMEOUT_SECONDS = 60.0


class GeminiImageGenerationError(RuntimeError):
    pass


async def generate_image(api_key: str, prompt: str) -> bytes:
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(
            _GEMINI_API_URL_TEMPLATE.format(model=_GEMINI_IMAGE_MODEL),
            params={"key": api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
        )
    if response.status_code >= 400:
        raise GeminiImageGenerationError(f"Gemini отказал в генерации изображения: {response.text}")
    payload = response.json()
    candidates = payload.get("candidates") or []
    if not candidates:
        raise GeminiImageGenerationError("Gemini не вернул ни одного варианта изображения.")
    for part in candidates[0].get("content", {}).get("parts", []):
        inline_data = part.get("inlineData")
        if inline_data and inline_data.get("data"):
            return base64.b64decode(inline_data["data"])
    raise GeminiImageGenerationError("Gemini вернул ответ без изображения — возможно, запрос отклонён политикой безопасности.")
