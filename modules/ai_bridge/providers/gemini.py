from __future__ import annotations

import re
from typing import Any

from modules.ai_bridge.providers.base import BrowserProviderAdapter


class GeminiAdapter(BrowserProviderAdapter):
    name = "gemini"
    url = "https://gemini.google.com/app"
    profile_dirname = "gemini"

    # Gemini's prompt input is a contenteditable rich-text box, not a <textarea>.
    prompt_box_selectors = (
        "div[role='textbox']",
        "[contenteditable='true']",
    )
    # Deliberately narrow: each of these matches only the model's reply, never
    # the user's own echoed message. Broader wrappers (e.g. a conversation
    # container) render the instant the user's message is submitted — before
    # Gemini has replied at all — which made the "has a response appeared"
    # check fire early and return the whole turn's text (question + answer)
    # instead of waiting for the actual reply.
    response_block_selectors = (
        "message-content",
        ".model-response-text",
        ".markdown",
        "[data-message-author-role='model']",
    )
    limit_markers = (
        "you've reached your daily limit",
        "you've reached your limit",
        "try again later",
        "temporarily unable to respond",
    )

    def _describe(self) -> str:
        return "Gemini (gemini.google.com)"

    async def _ensure_fast_mode(self, page: Any) -> None:
        # Best-effort: switch the model picker to the fast "Flash" model
        # rather than a slower "Pro"/"Thinking" variant, if the picker exists.
        picker = page.get_by_role("button", name=re.compile("flash", re.I))
        if await picker.count() > 0:
            await picker.first.click()
