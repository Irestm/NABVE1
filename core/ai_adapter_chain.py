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


def _gemini_candidate() -> PromptProviderPort | None:
    adapter = api_providers.get_gemini_adapter()
    if adapter is None:
        return None
    if quota_tracker.is_near_limit(adapter.name, limit=api_providers.GEMINI_RPM_LIMIT):
        return None
    if quota_tracker.is_near_daily_limit(adapter.name, limit=api_providers.GEMINI_RPD_LIMIT):
        return None
    return adapter


def candidate_chain(text: str) -> list[PromptProviderPort]:
    """The complexity-aware adapter order for a piece of free text —
    centralizes what used to live only in core/voice/ai_router.py's
    _candidate_adapters, so every other caller of this module (calendar
    event extraction, meeting summaries, task_orchestrator's planner,
    figma_control/blender_control command parsing, media recommendations,
    ui_automation grounding, messaging text cleanup, app_catalog, board
    games, ...) gets the same complexity-aware behavior instead of just the
    voice free-text path.

    Simple queries: the user's own Gemini key (if configured and under both
    its per-minute and per-day margins — see _gemini_candidate) goes first,
    since it's free and a real cloud model beats the small local one on
    anything past a trivial exchange; free_api_first_chain()'s existing
    order (Groq -> local -> ai_bridge browser chain) follows unchanged.

    Complex queries: neither Groq nor the local model has access to live
    data or the depth these need, so the base chain is reversed (cloud
    browser chain first) same as before — but the user's own Claude key (if
    configured) goes even before that, since it's a new capability (Claude
    isn't one of ai_bridge's four browser-automated providers at all) and a
    direct API call skips all of the browser chain's page-load/selector
    overhead. Neither key is ever dropped entirely on failure — both remain
    reachable at their position in the chain, and a caller that exhausts
    every adapter here still has the identical local-model/browser-chain
    floor free_api_first_chain() always guaranteed."""
    base = free_api_first_chain()
    if local_ai.is_complex_query(text):
        reversed_base = list(reversed(base))
        claude_adapter = api_providers.get_claude_adapter()
        return [claude_adapter, *reversed_base] if claude_adapter is not None else reversed_base
    gemini_adapter = _gemini_candidate()
    return [gemini_adapter, *base] if gemini_adapter is not None else base
