from __future__ import annotations

from core.ports import PromptProviderPort
from modules.ai_bridge import api_providers
from modules.ai_bridge.provider_manager import get_provider_manager
from modules.ai_bridge.quota_tracker import quota_tracker
from modules.hardware_adaptive import local_ai


def local_first_chain() -> list[PromptProviderPort]:
    """The local adaptive model first (if hardware supports one and it
    loaded successfully — see modules.hardware_adaptive.local_ai), then the
    ai_bridge cloud chain (Gemini -> ChatGPT -> DeepSeek -> Grok) as
    fallback. This is the default adapter order for any AI call that
    doesn't have its own reason to prefer cloud first; the one caller that
    does (core.voice.ai_router._candidate_adapters, which routes queries
    that look like they need live/external information straight to cloud)
    builds on top of this rather than duplicating it."""
    provider_manager = get_provider_manager()
    local_adapter = local_ai.get_adapter()
    if local_adapter is None:
        return [provider_manager]
    return [local_adapter, provider_manager]


def free_api_first_chain() -> list[PromptProviderPort]:
    """local_first_chain(), with the free-tier Groq API adapter (see
    modules.ai_bridge.api_providers) prepended when it's configured
    (GROQ_API_KEY set) and not close to its own rate limit. Quota is
    checked proactively here, before the adapter is even offered, rather
    than waiting for the API itself to reject a request — see
    modules.ai_bridge.quota_tracker for why. Without a configured key (or
    once its quota is near the limit for this window) this returns exactly
    local_first_chain()'s result, so the existing local-model/browser-chain
    behavior is the floor this feature can never regress below."""
    chain = local_first_chain()
    api_adapter = api_providers.get_adapter()
    if api_adapter is not None and not quota_tracker.is_near_limit(api_adapter.name):
        return [api_adapter, *chain]
    return chain
