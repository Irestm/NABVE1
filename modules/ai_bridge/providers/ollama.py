from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from modules.ai_bridge.providers.base import (
    AIResult,
    ChatMessage,
    ProviderBadResponse,
    ProviderHealth,
    ProviderUnavailable,
    parse_json_reply,
)
from modules.hardware_adaptive import local_ai
from modules.hardware_adaptive.inference_engine import LocalInferenceEngine
from modules.hardware_adaptive.local_ai import LocalEngineAdapter


def _as_ollama_messages(messages: list[ChatMessage]) -> list[dict[str, str]]:
    return [{"role": message["role"], "content": message["content"]} for message in messages]


class OllamaProvider:
    name = "ollama"
    experimental = False

    def _adapter(self) -> LocalEngineAdapter:
        adapter = local_ai.get_adapter()
        if adapter is None:
            raise ProviderUnavailable(self.name, local_ai.unavailable_reason() or "local model is not available")
        return adapter

    def is_ready(self) -> bool:
        return local_ai.get_adapter() is not None

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int,
    ) -> AIResult:
        adapter = self._adapter()
        try:
            text = await adapter.chat(_as_ollama_messages(messages), json_schema=json_schema, max_tokens=max_tokens)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(self.name, f"Ollama request failed: {exc}") from exc
        if not text:
            raise ProviderBadResponse(self.name, "empty reply")
        return AIResult(
            text=text,
            provider_name=self.name,
            parsed_json=parse_json_reply(self.name, text) if json_schema is not None else None,
        )

    async def stream(self, messages: list[ChatMessage], *, max_tokens: int) -> AsyncIterator[str]:
        adapter = self._adapter()
        try:
            async for delta in adapter.chat_stream(_as_ollama_messages(messages), max_tokens=max_tokens):
                yield delta
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(self.name, f"Ollama request failed: {exc}") from exc

    async def health(self) -> ProviderHealth:
        adapter = await asyncio.to_thread(local_ai.get_adapter)
        if adapter is None:
            return ProviderHealth(self.name, "unavailable", local_ai.unavailable_reason())
        started = time.monotonic()
        try:
            installed = await asyncio.to_thread(LocalInferenceEngine().installed_models)
        except httpx.HTTPError as exc:
            return ProviderHealth(self.name, "unavailable", f"Ollama не отвечает: {exc}")
        latency = int((time.monotonic() - started) * 1000)
        return ProviderHealth(self.name, "ok", f"tier={adapter.tier}, моделей: {len(installed)}", latency)
