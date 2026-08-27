from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator

from core.logger import get_logger
from modules.hardware_adaptive.hardware_detector import detect_hardware
from modules.hardware_adaptive.inference_engine import LocalInferenceEngine
from modules.hardware_adaptive.model_tiers import TIER_NONE, select_tier

logger = get_logger(__name__)

# The loaded model pins several GB of VRAM in the local Ollama server (see
# inference_engine.py) for as long as that server keeps it resident, even
# during long stretches where every request goes through ai_bridge instead
# (complex queries, or the local model simply not being asked anything for
# a while) — on a laptop-class GPU that VRAM is often wanted for other
# things. Unloading after a period of inactivity trades a one-time reload
# cost (a few seconds) on the next local-model request for giving that
# VRAM back in the meantime.
_IDLE_UNLOAD_SECONDS = 300
_IDLE_CHECK_INTERVAL_SECONDS = 30

# Simple heuristic, intentionally not a full classifier (per spec): anything
# that looks like it needs live/external information skips the local model
# and goes straight to ai_bridge's Gemini -> ChatGPT -> DeepSeek -> Grok
# chain. Grouped by category (rather than one flat tuple) so each kind of
# "needs fresh data" query is easy to audit/extend on its own — a quantized
# 3B/7B local model has no access to live information and will happily
# hallucinate a plausible-looking but wrong answer for any of these instead
# of admitting it doesn't know.
#
# Deliberately marker-only, no length threshold: a long-but-ordinary
# question (no live-data need) has no reason to lose access to the user's
# own configured Gemini API key (see core/ai_adapter_chain.py::
# candidate_chain — is_complex_query's only caller) and be routed to the
# much slower browser-automation chain instead. A length cutoff used to be
# here as a rough "probably needs deeper reasoning" proxy, but it was too
# blunt — it caught plenty of ordinary long questions that the API key
# would have answered fine, just to also (unreliably) catch some that
# actually needed live data, which the marker list already covers directly.
_WEB_SEARCH_MARKERS: tuple[str, ...] = (
    "загугли", "погугли", "нагугли",
    "найди в интернете", "поищи в интернете", "найди в гугле",
    "search the web", "google it", "look it up online",
)
_NEWS_MARKERS: tuple[str, ...] = (
    "актуальные новости", "последние новости", "свежие новости", "что нового",
    "latest news", "breaking news",
)
_LIVE_DATA_MARKERS: tuple[str, ...] = (
    "курс доллара", "курс евро", "курс валют", "курс рубля",
    "какая погода", "погода сегодня", "погода завтра", "прогноз погоды",
    "сколько сейчас времени", "который час", "какое сегодня число",
    "цена на", "стоимость акций", "котировки",
    "счёт матча", "счет матча", "результат матча",
    "exchange rate", "weather today", "weather forecast", "stock price",
)
_COMPLEX_MARKERS: tuple[str, ...] = _WEB_SEARCH_MARKERS + _NEWS_MARKERS + _LIVE_DATA_MARKERS


def is_complex_query(text: str) -> bool:
    normalized = text.lower()
    return any(marker in normalized for marker in _COMPLEX_MARKERS)


class LocalEngineAdapter:
    """Exposes LocalInferenceEngine through the same
    `send_prompt(text, *, fast_mode=True) -> str` surface as
    modules.ai_bridge.provider_manager.ProviderManager, so
    modules.ai_bridge.intent_classifier.classify() and core/voice/ai_router.py
    can use either one interchangeably. Also exposes `stream_prompt`, which
    ai_router uses (when the caller supports it) to speak the reply sentence
    by sentence as it's generated instead of waiting for the whole thing."""

    name = "local"

    def __init__(self, engine: LocalInferenceEngine, tier: str) -> None:
        self._engine = engine
        self._tier = tier

    def _ensure_loaded(self) -> None:
        # The idle watcher may have unloaded the model since this adapter was
        # handed out; reload it on demand rather than making the caller deal
        # with a stale/unavailable adapter.
        if not self._engine.is_loaded:
            logger.info("Local model was idle-unloaded; reloading tier='%s'", self._tier)
            self._engine.load_model(self._tier)

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
        _touch()
        return await asyncio.to_thread(self._generate, text)

    def _generate(self, text: str) -> str:
        self._ensure_loaded()
        try:
            return self._engine.generate(text)
        except RuntimeError:
            # _ensure_loaded()'s is_loaded check and this call aren't one
            # atomic step, so the idle-unload watcher (see local_ai._idle_watcher)
            # can still unload the model in between on rare timing — the
            # engine then raises exactly this RuntimeError. Reload once and
            # retry rather than surfacing a spurious failure for what should
            # be a transparent reload.
            self._ensure_loaded()
            return self._engine.generate(text)

    async def stream_prompt(self, text: str) -> AsyncIterator[str]:
        """Yields the reply as it's generated. Bridges the local engine's
        blocking/synchronous token stream onto the asyncio world via a
        background thread and a queue, since the generator can't be driven
        from the event loop directly without blocking it token by token."""
        _touch()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str | BaseException | None] = asyncio.Queue()

        def _produce() -> None:
            try:
                self._ensure_loaded()
                try:
                    for delta in self._engine.generate_stream(text):
                        loop.call_soon_threadsafe(queue.put_nowait, delta)
                except RuntimeError:
                    # Same idle-unload race as _generate() above — retry
                    # the whole stream once after reloading.
                    self._ensure_loaded()
                    for delta in self._engine.generate_stream(text):
                        loop.call_soon_threadsafe(queue.put_nowait, delta)
            except BaseException as exc:  # noqa: BLE001 - forwarded to the consumer, not swallowed
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=_produce, daemon=True, name="local-model-stream").start()

        while True:
            item = await queue.get()
            if item is None:
                return
            if isinstance(item, BaseException):
                raise item
            yield item


_engine: LocalInferenceEngine | None = None
_adapter: LocalEngineAdapter | None = None
_unavailable_reason: str | None = None
_initialized = False
_last_used_at = 0.0
_idle_watcher_started = False
_state_lock = threading.Lock()


def _touch() -> None:
    global _last_used_at
    with _state_lock:
        _last_used_at = time.monotonic()


def _idle_watcher() -> None:
    while True:
        time.sleep(_IDLE_CHECK_INTERVAL_SECONDS)
        try:
            with _state_lock:
                engine = _engine
                idle_for = time.monotonic() - _last_used_at
            if engine is not None and engine.is_loaded and idle_for >= _IDLE_UNLOAD_SECONDS:
                logger.info(
                    "Local model idle for %.0fs (>= %ds threshold); unloading to free VRAM",
                    idle_for, _IDLE_UNLOAD_SECONDS,
                )
                engine.unload()
        except Exception:
            # An uncaught exception here would silently kill this daemon
            # thread (Python's default unhandled-thread-exception behavior
            # is a stderr dump, not an assistant.log entry) — idle VRAM
            # unloading would then just stop happening for the rest of the
            # process's life with no trace of why. Same reasoning as
            # modules/plugin_agent/promotion_worker.py's poll-tick guard.
            logger.exception("Idle watcher tick failed")


def _start_idle_watcher() -> None:
    global _idle_watcher_started
    if _idle_watcher_started:
        return
    _idle_watcher_started = True
    threading.Thread(target=_idle_watcher, daemon=True, name="local-model-idle-watcher").start()


def _initialize() -> None:
    """Detects hardware and loads the local model on first use. Never raises:
    any failure (no CUDA GPU, Ollama not installed/reachable, or the model
    failing to pull) just leaves the local model unavailable so callers
    fall back to ai_bridge."""
    global _engine, _adapter, _unavailable_reason, _initialized
    if _initialized:
        return
    _initialized = True

    profile = detect_hardware()
    tier = select_tier(profile)
    if tier == TIER_NONE:
        _unavailable_reason = (
            f"No local model: hardware profile {profile} does not meet the minimum "
            "NVIDIA CUDA GPU/VRAM requirement; all requests will use ai_bridge."
        )
        logger.info(_unavailable_reason)
        return

    engine = LocalInferenceEngine()
    try:
        engine.load_model(tier)
    except Exception as exc:
        _unavailable_reason = f"Local model tier '{tier}' failed to load: {exc}"
        logger.warning(_unavailable_reason, exc_info=True)
        return

    _engine = engine
    _adapter = LocalEngineAdapter(engine, tier)
    _touch()
    _start_idle_watcher()
    logger.info("Local adaptive model ready (tier=%s)", tier)


def get_adapter() -> LocalEngineAdapter | None:
    """The local-model adapter if a supported CUDA GPU was detected and the
    model loaded successfully, else None — callers should fall back to
    ai_bridge. Hardware detection and model loading happen lazily on first
    call and are cached for the process lifetime."""
    _initialize()
    return _adapter


def unavailable_reason() -> str | None:
    """Human-readable reason the local model isn't available, or None if it
    is. Mainly for status/diagnostics endpoints."""
    _initialize()
    return _unavailable_reason
