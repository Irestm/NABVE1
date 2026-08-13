from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from core.logger import get_logger
from modules.ai_bridge.providers import PROVIDER_CLASSES, PROVIDER_ORDER
from modules.ai_bridge.providers.base import BrowserProviderAdapter
from modules.ai_bridge.state_store import StateStore
from modules.ai_bridge.system_prompt import apply_system_prompt

logger = get_logger(__name__)

_ACTIVE_KEY = "active_provider"
_LAST_RESET_KEY = "last_reset_date"


class AllProvidersExhaustedError(RuntimeError):
    pass


class ProviderManager:
    """Owns one adapter per provider and routes prompts to the currently
    active one, falling back through PROVIDER_ORDER (Gemini -> ChatGPT ->
    DeepSeek -> Grok) only when the active provider has genuinely hit its
    daily usage limit — not on every kind of failure. A not-logged-in session
    or a broken page layout won't recover by trying the next provider either
    (chances are it isn't logged in), so those fail fast for that call rather
    than opening three more browser windows and waiting on each one, which
    was both slow and visibly popped windows on screen for no benefit. On an
    actual limit-triggered switch, the reply is prefixed with a short spoken
    notice, since the user otherwise has no way to tell why this answer took
    longer than usual. The active provider (and when it was last reset for
    the day) is persisted so a restart doesn't reset back to Gemini mid-day.
    """

    # Satisfies core.ports.PromptProviderPort alongside
    # modules.hardware_adaptive.local_ai.LocalEngineAdapter, so
    # core/voice/ai_router.py can log/identify whichever adapter answered
    # without a defensive getattr(..., "name", adapter) fallback.
    name = "ai_bridge"

    def __init__(self, state_store: StateStore | None = None) -> None:
        self._adapters: dict[str, BrowserProviderAdapter] = {
            name: cls() for name, cls in PROVIDER_CLASSES.items()
        }
        self._store = state_store or StateStore()
        self._lock = asyncio.Lock()
        # Cached, not actively polled: updated whenever send_prompt observes a
        # provider's limit, so status() stays cheap (no browser round-trip per poll).
        self._limit_hit: dict[str, bool] = {name: False for name in PROVIDER_ORDER}

        self._active = self._store.get(_ACTIVE_KEY) or PROVIDER_ORDER[0]
        if self._active not in PROVIDER_ORDER:
            self._active = PROVIDER_ORDER[0]
        last_reset = self._store.get(_LAST_RESET_KEY)
        self._last_reset = last_reset or date.today().isoformat()
        if last_reset is None:
            self._store.set(_LAST_RESET_KEY, self._last_reset)
            self._store.set(_ACTIVE_KEY, self._active)

    @property
    def active_name(self) -> str:
        return self._active

    def _persist_active(self) -> None:
        self._store.set(_ACTIVE_KEY, self._active)

    def _maybe_daily_reset(self) -> None:
        today = date.today().isoformat()
        if self._last_reset == today:
            return
        logger.info("New day (%s) — resetting active AI provider to '%s'", today, PROVIDER_ORDER[0])
        self._active = PROVIDER_ORDER[0]
        self._last_reset = today
        self._limit_hit = {name: False for name in PROVIDER_ORDER}
        self._store.set(_LAST_RESET_KEY, today)
        self._persist_active()

    def _advance_to_next_provider(self) -> None:
        index = PROVIDER_ORDER.index(self._active)
        next_index = (index + 1) % len(PROVIDER_ORDER)
        self._active = PROVIDER_ORDER[next_index]
        self._persist_active()
        logger.warning("Switched active AI provider to '%s'", self._active)

    def get_adapter(self, name: str) -> BrowserProviderAdapter:
        return self._adapters[name]

    def get_active_adapter(self) -> BrowserProviderAdapter:
        return self._adapters[self._active]

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
        # Applied once, here, for every provider and every caller (ai_bridge_ask,
        # intent classification, voice question fallback) so the assistant's tone
        # never depends on which provider ends up answering.
        prompt = apply_system_prompt(text)

        async with self._lock:
            self._maybe_daily_reset()

            last_error: Exception | None = None
            switched = False
            for _attempt in range(len(PROVIDER_ORDER)):
                name = self._active
                adapter = self._adapters[name]

                try:
                    await adapter.open()
                    if await adapter.is_limit_reached():
                        self._limit_hit[name] = True
                        logger.warning("Provider '%s' has hit its daily limit; switching", name)
                        self._advance_to_next_provider()
                        switched = True
                        continue

                    reply = await adapter.send_prompt(prompt, fast_mode=fast_mode)
                    self._limit_hit[name] = False
                    if switched:
                        reply = (
                            "Переключаюсь на другой источник — это может занять немного "
                            f"больше времени. {reply}"
                        )
                    return reply
                except Exception as exc:
                    last_error = exc
                    try:
                        limited = await adapter.is_limit_reached()
                    except Exception:
                        # last_error (the send_prompt failure above) is
                        # already logged via logger.exception a few lines
                        # below when this probe says "not limited" — but if
                        # THIS probe is what's actually broken, that
                        # specific failure would otherwise leave no trace
                        # anywhere.
                        logger.debug("Could not confirm limit status for '%s'", name, exc_info=True)
                        limited = False
                    self._limit_hit[name] = limited

                    if not limited:
                        # Not a confirmed daily-limit situation (not logged
                        # in, changed page layout, timed out, ...) — the
                        # other providers are usually not logged in either,
                        # so cascading through all of them here is normally
                        # futile and costly (each attempt opens a real
                        # browser window and can take many seconds). Fail
                        # fast for this call instead of trying three more.
                        logger.exception("Provider '%s' failed (not a limit issue)", name)
                        raise

                    logger.warning("Provider '%s' has hit its daily limit; switching", name)
                    self._advance_to_next_provider()
                    switched = True
                    continue

            raise AllProvidersExhaustedError(
                "All AI providers (Gemini, ChatGPT, DeepSeek, Grok) have reached their daily limit."
            ) from last_error

    async def reveal_active(self) -> None:
        await self._adapters[self._active].reveal()

    async def hide_active(self) -> None:
        await self._adapters[self._active].hide()

    async def close_all(self) -> None:
        await asyncio.gather(*(adapter.close() for adapter in self._adapters.values()))

    def status(self) -> dict[str, Any]:
        return {
            "active_provider": self._active,
            "order": list(PROVIDER_ORDER),
            "last_reset_date": self._last_reset,
            "limit_reached": dict(self._limit_hit),
        }


_manager: ProviderManager | None = None


def get_provider_manager() -> ProviderManager:
    global _manager
    if _manager is None:
        _manager = ProviderManager()
    return _manager
