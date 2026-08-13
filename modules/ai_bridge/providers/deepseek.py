from __future__ import annotations

import re
from typing import Any

from modules.ai_bridge.providers.base import BrowserProviderAdapter


class DeepSeekAdapter(BrowserProviderAdapter):
    name = "deepseek"
    url = "https://chat.deepseek.com/"
    profile_dirname = "deepseek"

    prompt_box_selectors = (
        "#chat-input",
        "textarea",
        "[contenteditable='true']",
    )
    response_block_selectors = (
        ".markdown",
        "[class*='markdown']",
    )
    limit_markers = (
        "reached the usage limit",
        "current usage limit",
        "too many requests",
        "reached your daily limit",
    )

    def _describe(self) -> str:
        return "DeepSeek (chat.deepseek.com)"

    async def _ensure_fast_mode(self, page: Any) -> None:
        # Best-effort: make sure the slower "DeepThink"/R1 reasoning toggle is
        # off so prompts go to the fast default chat model.
        toggle = page.get_by_role("button", name=re.compile("deepthink", re.I))
        if await toggle.count() == 0:
            return
        pressed = await toggle.first.get_attribute("aria-pressed")
        if pressed == "true":
            await toggle.first.click()
