from __future__ import annotations

from modules.ai_bridge.providers.experimental.base import AIProviderAdapter, BrowserProviderAdapter
from modules.ai_bridge.providers.experimental.chatgpt import ChatGPTAdapter
from modules.ai_bridge.providers.experimental.deepseek import DeepSeekAdapter
from modules.ai_bridge.providers.experimental.gemini import GeminiAdapter
from modules.ai_bridge.providers.experimental.grok import GrokAdapter

# Fixed fallback order: Gemini -> ChatGPT -> DeepSeek -> Grok.
PROVIDER_CLASSES: dict[str, type[BrowserProviderAdapter]] = {
    "gemini": GeminiAdapter,
    "chatgpt": ChatGPTAdapter,
    "deepseek": DeepSeekAdapter,
    "grok": GrokAdapter,
}
PROVIDER_ORDER: tuple[str, ...] = ("gemini", "chatgpt", "deepseek", "grok")

__all__ = [
    "AIProviderAdapter",
    "BrowserProviderAdapter",
    "GeminiAdapter",
    "ChatGPTAdapter",
    "DeepSeekAdapter",
    "GrokAdapter",
    "PROVIDER_CLASSES",
    "PROVIDER_ORDER",
]
