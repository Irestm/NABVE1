from __future__ import annotations

import httpx

from core.config import settings
from core.logger import get_logger
from core.secret_store import get_secret
from modules.ai_bridge.quota_tracker import QuotaTracker, quota_tracker
from modules.ai_bridge.system_prompt import apply_system_prompt

logger = get_logger(__name__)

GEMINI_API_KEY_SECRET_NAME = "gemini_api_key"
CLAUDE_API_KEY_SECRET_NAME = "claude_api_key"

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


_GEMINI_API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_GEMINI_MODEL = "gemini-2.5-flash"

# Conservative margins under Gemini's actual free-tier limits (10 RPM / 500
# RPD as of 2026-08, per Google's docs — both change without notice, same
# caution as Groq's _MAX_REQUESTS_PER_WINDOW above). The goal is the same:
# stop offering the adapter before a request would get rejected — or, worse,
# before enough rejected/back-to-back requests risk the key getting flagged
# for hammering the rate limit — not react after the fact.
GEMINI_RPM_LIMIT = 6
GEMINI_RPD_LIMIT = 400


class GeminiApiAdapter:
    """User-supplied Gemini key (see core/secret_store.py), offered ahead of
    the local on-device model for queries modules.hardware_adaptive.local_ai
    does NOT flag as complex (see core/ai_adapter_chain.py) — free, and a
    real cloud model beats the small local one on anything past a trivial
    exchange. Both quota checks (is_near_limit/is_near_daily_limit) are the
    caller's job, same split as Groq above: checked before this adapter is
    even offered, recorded here once a call actually goes out."""

    name = "gemini_api"

    def __init__(self, api_key: str, quota: QuotaTracker) -> None:
        self._api_key = api_key
        self._quota = quota

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
        prompt = apply_system_prompt(text)
        self._quota.record_request(self.name)
        self._quota.record_daily_request(self.name)
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _GEMINI_API_URL_TEMPLATE.format(model=_GEMINI_MODEL),
                params={"key": self._api_key},
                json={"contents": [{"parts": [{"text": prompt}]}]},
            )
        response.raise_for_status()
        payload = response.json()
        return payload["candidates"][0]["content"]["parts"][0]["text"]


_gemini_adapter: GeminiApiAdapter | None = None
_gemini_adapter_key: str | None = None


def get_gemini_adapter() -> GeminiApiAdapter | None:
    """Unlike get_adapter() (Groq, env-var configured, fixed for the process
    lifetime), the Gemini key is user-supplied via Settings and can change
    at any time — so this re-reads the stored secret on every call instead
    of caching permanently, the same "don't cache a runtime-togglable
    setting" rule modules/custom_commands/dispatcher.py's requires_confirmation()
    already follows. Still cheap: the adapter object itself is only rebuilt
    when the stored key actually changed."""
    global _gemini_adapter, _gemini_adapter_key
    api_key = get_secret(GEMINI_API_KEY_SECRET_NAME)
    if not api_key:
        _gemini_adapter = None
        _gemini_adapter_key = None
        return None
    if _gemini_adapter is None or _gemini_adapter_key != api_key:
        _gemini_adapter = GeminiApiAdapter(api_key, quota_tracker)
        _gemini_adapter_key = api_key
    return _gemini_adapter


_CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
_CLAUDE_MODEL = "claude-sonnet-5"
_CLAUDE_ANTHROPIC_VERSION = "2023-06-01"
_CLAUDE_MAX_TOKENS = 1024


class ClaudeApiAdapter:
    """Anthropic's own API, offered ahead of the slow ai_bridge
    browser-automation chain for queries local_ai.is_complex_query flags as
    complex (see core/ai_adapter_chain.py) — Claude isn't one of the four
    browser-automated ai_bridge providers at all, so a configured key here
    is a new capability, not just a faster path to one that already
    existed. No free tier, so unlike Gemini there's no proactive rate-limit
    gate here — Anthropic's paid-tier limits are generous enough that a
    single-user assistant hitting them isn't a realistic concern."""

    name = "claude_api"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
        prompt = apply_system_prompt(text)
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _CLAUDE_API_URL,
                headers={"x-api-key": self._api_key, "anthropic-version": _CLAUDE_ANTHROPIC_VERSION},
                json={
                    "model": _CLAUDE_MODEL,
                    "max_tokens": _CLAUDE_MAX_TOKENS,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        response.raise_for_status()
        payload = response.json()
        return payload["content"][0]["text"]


_claude_adapter: ClaudeApiAdapter | None = None
_claude_adapter_key: str | None = None


def get_claude_adapter() -> ClaudeApiAdapter | None:
    """Same re-read-every-call reasoning as get_gemini_adapter() above."""
    global _claude_adapter, _claude_adapter_key
    api_key = get_secret(CLAUDE_API_KEY_SECRET_NAME)
    if not api_key:
        _claude_adapter = None
        _claude_adapter_key = None
        return None
    if _claude_adapter is None or _claude_adapter_key != api_key:
        _claude_adapter = ClaudeApiAdapter(api_key)
        _claude_adapter_key = api_key
    return _claude_adapter
