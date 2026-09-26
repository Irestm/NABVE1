from __future__ import annotations

from modules.ai_bridge.providers.openai_compatible import OpenAICompatibleProvider

DEFAULT_MODEL = "deepseek-chat"


class DeepSeekApiProvider(OpenAICompatibleProvider):
    name = "deepseek_api"
    base_url = "https://api.deepseek.com"
    json_mode = "json_object"
    max_tokens_field = "max_tokens"

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        super().__init__(model)
