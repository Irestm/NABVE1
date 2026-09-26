from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

from core.secret_store import delete_secret, get_secret, store_secret

GEMINI_API_KEY_SECRET_NAME = "gemini_api_key"
CLAUDE_API_KEY_SECRET_NAME = "claude_api_key"
OPENAI_API_KEY_SECRET_NAME = "openai_api_key"
DEEPSEEK_API_KEY_SECRET_NAME = "deepseek_api_key"
GROQ_API_KEY_SECRET_NAME = "groq_api_key"

_CACHE_TTL_SECONDS = 30.0


@dataclass(frozen=True)
class KeySpec:
    secret_name: str
    env_var: str


KEY_SPECS: dict[str, KeySpec] = {
    "anthropic_api": KeySpec(CLAUDE_API_KEY_SECRET_NAME, "ANTHROPIC_API_KEY"),
    "openai_api": KeySpec(OPENAI_API_KEY_SECRET_NAME, "OPENAI_API_KEY"),
    "gemini_api": KeySpec(GEMINI_API_KEY_SECRET_NAME, "GEMINI_API_KEY"),
    "deepseek_api": KeySpec(DEEPSEEK_API_KEY_SECRET_NAME, "DEEPSEEK_API_KEY"),
    "groq_api": KeySpec(GROQ_API_KEY_SECRET_NAME, "GROQ_API_KEY"),
}

_cache: dict[str, tuple[float, str | None]] = {}
_cache_lock = threading.Lock()


def read_key(provider_name: str) -> str | None:
    spec = KEY_SPECS[provider_name]
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(provider_name)
        if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]
    value = get_secret(spec.secret_name) or os.environ.get(spec.env_var) or None
    with _cache_lock:
        _cache[provider_name] = (now, value)
    return value


def save_key(provider_name: str, value: str) -> None:
    store_secret(KEY_SPECS[provider_name].secret_name, value)
    invalidate(provider_name)


def remove_key(provider_name: str) -> None:
    delete_secret(KEY_SPECS[provider_name].secret_name)
    invalidate(provider_name)


def invalidate(provider_name: str | None = None) -> None:
    with _cache_lock:
        if provider_name is None:
            _cache.clear()
        else:
            _cache.pop(provider_name, None)
