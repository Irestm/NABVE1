from __future__ import annotations

from modules.ai_bridge.providers.base import AIProviderAdapter, BrowserProviderAdapter
from modules.ai_bridge.providers.chatgpt import ChatGPTAdapter
from modules.ai_bridge.providers.deepseek import DeepSeekAdapter
from modules.ai_bridge.providers.gemini import GeminiAdapter
from modules.ai_bridge.providers.grok import GrokAdapter

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
