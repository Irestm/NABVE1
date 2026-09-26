from __future__ import annotations

import time
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

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
from modules.ai_bridge.quota_tracker import QuotaTracker, quota_tracker

DEFAULT_MODEL = "gemini-2.5-flash"
GEMINI_RPM_LIMIT = 6
GEMINI_RPD_LIMIT = 400


def map_gemini_error(provider_name: str, exc: Exception) -> ProviderError:
    if isinstance(exc, genai_errors.APIError):
        if exc.code == 429:
            return ProviderRateLimited(provider_name, "rate limit reached")
        if exc.code in (401, 403) or (exc.code == 400 and "API key" in str(exc)):
            return ProviderAuthError(provider_name, "API key rejected")
        if exc.code >= 500:
            return ProviderUnavailable(provider_name, f"server error {exc.code}")
        return ProviderBadResponse(provider_name, f"request rejected ({exc.code}): {exc}")
    return ProviderUnavailable(provider_name, str(exc))


class GeminiApiProvider:
    name = "gemini_api"
    experimental = False

    def __init__(self, model: str = DEFAULT_MODEL, quota: QuotaTracker = quota_tracker) -> None:
        self._model = model
        self._quota = quota
        self._client: genai.Client | None = None
        self._client_key: str | None = None

    def _client_for_current_key(self) -> genai.Client:
        api_key = read_key(self.name)
        if not api_key:
            raise ProviderAuthError(self.name, "API key is not configured")
        if self._client is None or self._client_key != api_key:
            self._client = genai.Client(api_key=api_key)
            self._client_key = api_key
        return self._client

    def _near_quota(self) -> bool:
        return self._quota.is_near_limit(self.name, limit=GEMINI_RPM_LIMIT) or self._quota.is_near_daily_limit(
            self.name, limit=GEMINI_RPD_LIMIT
        )

    def is_ready(self) -> bool:
        return read_key(self.name) is not None and not self._near_quota()

    def requests_used_today(self) -> int:
        return self._quota.daily_count(self.name)

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int,
    ) -> AIResult:
        client = self._client_for_current_key()
        system, conversation = split_system(messages)
        contents = [
            genai_types.Content(
                role="model" if message["role"] == "assistant" else "user",
                parts=[genai_types.Part(text=message["content"])],
            )
            for message in conversation
        ]
        config = genai_types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            response_mime_type="application/json" if json_schema is not None else None,
            response_json_schema=json_schema,
        )
        self._quota.record_request(self.name)
        self._quota.record_daily_request(self.name)
        try:
            response = await client.aio.models.generate_content(model=self._model, contents=contents, config=config)
        except genai_errors.APIError as exc:
            raise map_gemini_error(self.name, exc) from exc
        except OSError as exc:
            raise ProviderUnavailable(self.name, f"connection failed: {exc}") from exc
        text = response.text or ""
        if not text.strip():
            raise ProviderBadResponse(self.name, "empty reply")
        metadata = response.usage_metadata
        usage = (
            {
                "input_tokens": metadata.prompt_token_count or 0,
                "output_tokens": metadata.candidates_token_count or 0,
            }
            if metadata is not None
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
            await self._client_for_current_key().aio.models.get(model=self._model)
        except genai_errors.APIError as exc:
            return health_from_error(self.name, map_gemini_error(self.name, exc))
        except OSError as exc:
            return ProviderHealth(self.name, "unavailable", str(exc))
        extra = {"requests_used_today": self.requests_used_today(), "daily_limit": GEMINI_RPD_LIMIT}
        if self._near_quota():
            return ProviderHealth(self.name, "rate_limited", "близко к лимиту бесплатного тарифа", extra=extra)
        return ProviderHealth(self.name, "ok", self._model, int((time.monotonic() - started) * 1000), extra=extra)
