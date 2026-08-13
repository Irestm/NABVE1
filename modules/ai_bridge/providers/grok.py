from __future__ import annotations

import re
from typing import Any

from modules.ai_bridge.providers.base import BrowserProviderAdapter


class GrokAdapter(BrowserProviderAdapter):
    name = "grok"
    url = "https://grok.com/"
    profile_dirname = "grok"

    prompt_box_selectors = (
        "textarea",
        "[contenteditable='true']",
    )
    response_block_selectors = (
        "[class*='message-bubble']",
        ".prose",
    )
    limit_markers = (
        "you've reached your limit",
        "upgrade to supergrok",
        "you've used all your free",
        "come back later",
    )

    def _describe(self) -> str:
        return "Grok (grok.com)"

    async def _ensure_fast_mode(self, page: Any) -> None:
        # Best-effort: disable the "Think" toggle so the prompt goes to Grok's
        # fast default mode rather than an extended-reasoning mode.
        toggle = page.get_by_role("button", name=re.compile("^think$", re.I))
        if await toggle.count() == 0:
            return
        pressed = await toggle.first.get_attribute("aria-pressed")
        if pressed == "true":
            await toggle.first.click()
