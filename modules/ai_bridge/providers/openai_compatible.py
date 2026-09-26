from __future__ import annotations

import time
from typing import Any, Literal

import openai

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
    with_schema_instruction,
)
from modules.ai_bridge.providers.keys import read_key
from modules.ai_bridge.quota_tracker import QuotaTracker

_TIMEOUT_SECONDS = 30.0
_MAX_RETRIES = 1

JsonMode = Literal["json_schema", "json_object"]


def map_openai_error(provider_name: str, exc: Exception) -> ProviderError:
    if isinstance(exc, openai.RateLimitError):
        return ProviderRateLimited(provider_name, "rate limit reached")
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return ProviderAuthError(provider_name, "API key rejected")
    if isinstance(exc, openai.APIConnectionError):
        return ProviderUnavailable(provider_name, f"connection failed: {exc}")
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code == 402:
            return ProviderRateLimited(provider_name, "insufficient balance")
        if exc.status_code >= 500:
            return ProviderUnavailable(provider_name, f"server error {exc.status_code}")
        return ProviderBadResponse(provider_name, f"request rejected ({exc.status_code}): {exc.message}")
    return ProviderUnavailable(provider_name, str(exc))


class OpenAICompatibleProvider:
    name: str = "openai_compatible"
    experimental = False
    base_url: str | None = None
    json_mode: JsonMode = "json_schema"
    max_tokens_field: str = "max_completion_tokens"
    rpm_limit: int | None = None
    rpd_limit: int | None = None

    def __init__(self, model: str, quota: QuotaTracker | None = None) -> None:
        self._model = model
        self._quota = quota
        self._client: openai.AsyncOpenAI | None = None
        self._client_key: str | None = None

    def _client_for_current_key(self) -> openai.AsyncOpenAI:
        api_key = read_key(self.name)
        if not api_key:
            raise ProviderAuthError(self.name, "API key is not configured")
        if self._client is None or self._client_key != api_key:
            self._client = openai.AsyncOpenAI(
                api_key=api_key, base_url=self.base_url, timeout=_TIMEOUT_SECONDS, max_retries=_MAX_RETRIES
            )
            self._client_key = api_key
        return self._client

    def _near_quota(self) -> bool:
        if self._quota is None:
            return False
        if self.rpm_limit is not None and self._quota.is_near_limit(self.name, limit=self.rpm_limit):
            return True
        return self.rpd_limit is not None and self._quota.is_near_daily_limit(self.name, limit=self.rpd_limit)

    def is_ready(self) -> bool:
        return read_key(self.name) is not None and not self._near_quota()

    def _record_request(self) -> None:
        if self._quota is None:
            return
        self._quota.record_request(self.name)
        if self.rpd_limit is not None:
            self._quota.record_daily_request(self.name)

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int,
    ) -> AIResult:
        client = self._client_for_current_key()
        request: dict[str, Any] = {"model": self._model, self.max_tokens_field: max_tokens}
        prepared = messages
        if json_schema is not None:
            if self.json_mode == "json_schema":
                request["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "result", "schema": json_schema, "strict": True},
                }
            else:
                prepared = with_schema_instruction(messages, json_schema)
                request["response_format"] = {"type": "json_object"}
        request["messages"] = [{"role": message["role"], "content": message["content"]} for message in prepared]
        self._record_request()
        try:
            response = await client.chat.completions.create(**request)
        except openai.OpenAIError as exc:
            raise map_openai_error(self.name, exc) from exc
        if not response.choices:
            raise ProviderBadResponse(self.name, "no choices in reply")
        text = response.choices[0].message.content or ""
        if not text.strip():
            raise ProviderBadResponse(self.name, "empty reply")
        usage = (
            {"input_tokens": response.usage.prompt_tokens, "output_tokens": response.usage.completion_tokens}
            if response.usage is not None
            else None
        )
        return AIResult(
            text=text,
            provider_name=self.name,
            parsed_json=parse_json_reply(self.name, text) if json_schema is not None else None,
            usage=usage,
        )

    async def health(self) -> ProviderHealth:
        if read_key(self.name) is None:
            return ProviderHealth(self.name, "not_configured", "API-ключ не задан")
        started = time.monotonic()
        try:
            await self._client_for_current_key().models.retrieve(self._model)
        except openai.OpenAIError as exc:
            return health_from_error(self.name, map_openai_error(self.name, exc))
        if self._near_quota():
            return ProviderHealth(self.name, "rate_limited", "близко к лимиту бесплатного тарифа")
        return ProviderHealth(self.name, "ok", self._model, int((time.monotonic() - started) * 1000))
