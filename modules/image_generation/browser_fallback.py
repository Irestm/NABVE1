from __future__ import annotations

import base64

from core.logger import get_logger
from modules.ai_bridge.provider_manager import get_provider_manager

logger = get_logger(__name__)

_IMAGE_WAIT_TIMEOUT_MS = 60_000
# Best-effort, not verified against a live Gemini session — same caveat as
# modules/youtube_control/browser_control.py's selectors: Gemini's web UI
# markup isn't ours to pin down, so this is the most plausible selector for
# a freshly generated image, not a guarantee. If Gemini changes its layout,
# this raises BrowserImageGenerationError with a clear message rather than
# silently returning nothing.
_GENERATED_IMAGE_SELECTOR = "img[src^='blob:'], img[src^='data:image']"


class BrowserImageGenerationError(RuntimeError):
    pass


async def generate_image(prompt: str) -> bytes:
    """Falls back to the same authenticated Gemini browser session
    modules.ai_bridge already maintains for text chat (see
    modules.ai_bridge.providers.gemini.GeminiAdapter) rather than opening a
    second, separate browser context — one login, reused for both."""
    adapter = get_provider_manager().get_adapter("gemini")
    page = await adapter.open()

    prompt_box = None
    for selector in adapter.prompt_box_selectors:
        try:
            await page.wait_for_selector(selector, timeout=10_000, state="visible")
            prompt_box = page.locator(selector).first
            break
        except Exception:
            continue
    if prompt_box is None:
        raise BrowserImageGenerationError("Не удалось найти поле ввода на странице Gemini.")

    await prompt_box.click()
    await prompt_box.fill(prompt)
    await prompt_box.press("Enter")

    try:
        await page.wait_for_selector(_GENERATED_IMAGE_SELECTOR, timeout=_IMAGE_WAIT_TIMEOUT_MS, state="visible")
    except Exception as exc:
        raise BrowserImageGenerationError(
            "Gemini не сгенерировал изображение за отведённое время (или изменилась вёрстка сайта)."
        ) from exc

    image_src = await page.locator(_GENERATED_IMAGE_SELECTOR).last.get_attribute("src")
    if not image_src:
        raise BrowserImageGenerationError("Не удалось получить сгенерированное изображение со страницы Gemini.")

    if image_src.startswith("data:image"):
        _, _, encoded = image_src.partition(",")
        return base64.b64decode(encoded)

    base64_data = await page.evaluate(
        """async (src) => {
            const response = await fetch(src);
            const buffer = await response.arrayBuffer();
            let binary = '';
            const bytes = new Uint8Array(buffer);
            for (const byte of bytes) { binary += String.fromCharCode(byte); }
            return btoa(binary);
        }""",
        image_src,
    )
    return base64.b64decode(base64_data)
