from __future__ import annotations

import time
from typing import Any

import anthropic

from modules.ai_bridge.providers.base import (
    AIResult,
    ChatMessage,
    ProviderAuthError,
    ProviderBadResponse,
    ProviderError,
    ProviderHealth,
    ProviderRateLimited,
    ProviderUnavailable,
    health_from_error,
    parse_json_reply,
    split_system,
)
from modules.ai_bridge.providers.keys import read_key

DEFAULT_MODEL = "claude-sonnet-5"
_TIMEOUT_SECONDS = 30.0
_MAX_RETRIES = 1


def map_anthropic_error(provider_name: str, exc: Exception) -> ProviderError:
    if isinstance(exc, anthropic.RateLimitError):
        return ProviderRateLimited(provider_name, "rate limit reached")
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return ProviderAuthError(provider_name, "API key rejected")
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderUnavailable(provider_name, f"connection failed: {exc}")
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code >= 500:
            return ProviderUnavailable(provider_name, f"server error {exc.status_code}")
        return ProviderBadResponse(provider_name, f"request rejected ({exc.status_code}): {exc.message}")
    return ProviderUnavailable(provider_name, str(exc))


class AnthropicApiProvider:
    name = "anthropic_api"
    experimental = False

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self._model = model
        self._client: anthropic.AsyncAnthropic | None = None
        self._client_key: str | None = None

    def _client_for_current_key(self) -> anthropic.AsyncAnthropic:
        api_key = read_key(self.name)
        if not api_key:
            raise ProviderAuthError(self.name, "API key is not configured")
        if self._client is None or self._client_key != api_key:
            self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=_TIMEOUT_SECONDS, max_retries=_MAX_RETRIES)
            self._client_key = api_key
        return self._client

    def is_ready(self) -> bool:
        return read_key(self.name) is not None

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int,
    ) -> AIResult:
        client = self._client_for_current_key()
        system, conversation = split_system(messages)
        request: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": [{"role": message["role"], "content": message["content"]} for message in conversation],
        }
        if system:
            request["system"] = system
        if json_schema is not None:
            request["output_config"] = {"format": {"type": "json_schema", "schema": json_schema}}
        try:
            response = await client.messages.create(**request)
        except anthropic.AnthropicError as exc:
            raise map_anthropic_error(self.name, exc) from exc
        if response.stop_reason == "refusal":
            raise ProviderBadResponse(self.name, "model declined the request")
        text = "".join(block.text for block in response.content if block.type == "text")
        if not text:
            raise ProviderBadResponse(self.name, "empty reply")
        return AIResult(
            text=text,
            provider_name=self.name,
            parsed_json=parse_json_reply(self.name, text) if json_schema is not None else None,
            usage={"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
        )

    async def health(self) -> ProviderHealth:
        if not self.is_ready():
            return ProviderHealth(self.name, "not_configured", "API-ключ не задан")
        started = time.monotonic()
        try:
            await self._client_for_current_key().models.retrieve(self._model)
        except anthropic.AnthropicError as exc:
            return health_from_error(self.name, map_anthropic_error(self.name, exc))
        return ProviderHealth(self.name, "ok", self._model, int((time.monotonic() - started) * 1000))

