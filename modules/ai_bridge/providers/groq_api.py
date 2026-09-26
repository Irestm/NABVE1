from __future__ import annotations

from modules.ai_bridge.providers.openai_compatible import OpenAICompatibleProvider
from modules.ai_bridge.quota_tracker import QuotaTracker, quota_tracker

DEFAULT_MODEL = "llama-3.3-70b-versatile"
GROQ_RPM_LIMIT = 20


class GroqApiProvider(OpenAICompatibleProvider):
    name = "groq_api"
    base_url = "https://api.groq.com/openai/v1"
    json_mode = "json_object"
    max_tokens_field = "max_tokens"
    rpm_limit = GROQ_RPM_LIMIT

    def __init__(self, model: str = DEFAULT_MODEL, quota: QuotaTracker = quota_tracker) -> None:
        super().__init__(model, quota)
