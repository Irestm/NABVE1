from __future__ import annotations

from modules.ai_bridge.providers.openai_compatible import OpenAICompatibleProvider

DEFAULT_MODEL = "gpt-5-mini"


class OpenAIApiProvider(OpenAICompatibleProvider):
    name = "openai_api"

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        super().__init__(model)
