from __future__ import annotations

import httpx

from core.config import settings
from core.logger import get_logger
from modules.ai_bridge.quota_tracker import QuotaTracker, quota_tracker
from modules.ai_bridge.system_prompt import apply_system_prompt

logger = get_logger(__name__)

_GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
# A current, fast, generous-free-tier Groq-hosted model. Groq periodically
# retires older model names; if this one ever 404s, swap it here — nothing
# else in this module hardcodes a model name.
_GROQ_MODEL = "llama-3.3-70b-versatile"
_REQUEST_TIMEOUT_SECONDS = 15.0


class GroqApiAdapter:
    """Free-tier Groq API (LPU inference — very low latency, no cost within
    the free rate limit) offered as the fastest tier ahead of the local
    model and the ai_bridge browser-automation chain (see
    core/ai_adapter_chain.py::free_api_first_chain). Implements the same
    core.ports.PromptProviderPort shape as
    modules.ai_bridge.provider_manager.ProviderManager and
    modules.hardware_adaptive.local_ai.LocalEngineAdapter, so
    core/voice/ai_router.py can use it interchangeably with either.

    Deliberately never a paid fallback: GroqQuotaTracker (see quota_tracker.py)
    is checked by the caller (free_api_first_chain) BEFORE this adapter is
    even offered, and on any error here core/voice/ai_router.py's own
    adapter loop just moves on to the next adapter in the chain — a failure
    or exhausted quota degrades to the existing local/browser path, it never
    blocks an answer."""

    name = "groq_api"

    def __init__(self, api_key: str, quota: QuotaTracker) -> None:
        self._api_key = api_key
        self._quota = quota

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
        prompt = apply_system_prompt(text)
        self._quota.record_request(self.name)
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _GROQ_API_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": _GROQ_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        response.raise_for_status()
        payload = response.json()
        return payload["choices"][0]["message"]["content"]


_adapter: GroqApiAdapter | None = None
_adapter_initialized = False


def get_adapter() -> GroqApiAdapter | None:
    """The Groq adapter if GROQ_API_KEY is configured, else None — callers
    fall back to whatever chain they'd otherwise use. Lazily constructed and
    cached for the process lifetime, matching
    modules.hardware_adaptive.local_ai.get_adapter()'s shape."""
    global _adapter, _adapter_initialized
    if _adapter_initialized:
        return _adapter
    _adapter_initialized = True
    if not settings.groq_api_key:
        logger.info("GROQ_API_KEY not set: free-tier fast AI tier disabled")
        return None
    _adapter = GroqApiAdapter(settings.groq_api_key, quota_tracker)
    return _adapter
