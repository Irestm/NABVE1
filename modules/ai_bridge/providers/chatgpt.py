from __future__ import annotations

import re
from typing import Any

from modules.ai_bridge.providers.base import BrowserProviderAdapter


class ChatGPTAdapter(BrowserProviderAdapter):
    name = "chatgpt"
    url = "https://chatgpt.com/"
    profile_dirname = "chatgpt"

    prompt_box_selectors = (
        "#prompt-textarea",
        "[contenteditable='true']",
        "textarea",
    )
    response_block_selectors = (
        "[data-message-author-role='assistant']",
        ".markdown",
    )
    limit_markers = (
        "you've reached the current usage cap",
        "you've reached your message limit",
        "you've hit the free plan limit",
        "try again after",
        "you've reached the limit of messages",
    )

    def _describe(self) -> str:
        return "ChatGPT (chatgpt.com)"

    async def _ensure_fast_mode(self, page: Any) -> None:
        # Best-effort: open the model switcher and pick a fast/mini model
        # instead of a slower reasoning model, if the picker exists.
        switcher = page.get_by_role("button", name=re.compile("model|gpt", re.I))
        if await switcher.count() == 0:
            return
        await switcher.first.click()
        option = page.get_by_role("menuitemradio", name=re.compile("mini|fast|instant", re.I))
        if await option.count() > 0:
            await option.first.click()
        else:
            # Close the picker again if nothing matched, so it doesn't sit open.
            await page.keyboard.press("Escape")
