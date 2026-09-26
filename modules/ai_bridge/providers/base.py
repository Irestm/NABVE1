from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypedDict, runtime_checkable

Role = Literal["system", "user", "assistant"]
HealthStatus = Literal["ok", "not_configured", "disabled", "auth_error", "rate_limited", "unavailable"]
ChainKind = Literal["default", "complex"]


class ChatMessage(TypedDict):
    role: Role
    content: str


@dataclass(frozen=True)
class AIResult:
    text: str
    provider_name: str
    parsed_json: Any | None = None
    usage: dict[str, int] | None = None


@dataclass(frozen=True)
class ProviderHealth:
    name: str
    status: HealthStatus
    detail: str | None = None
    latency_ms: int | None = None
    experimental: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class ProviderError(RuntimeError):
    def __init__(self, provider_name: str, message: str) -> None:
        super().__init__(f"{provider_name}: {message}")
        self.provider_name = provider_name


class ProviderUnavailable(ProviderError):
    pass


class ProviderRateLimited(ProviderError):
    pass


class ProviderAuthError(ProviderError):
    pass


class ProviderBadResponse(ProviderError):
    pass


class AllProvidersFailed(RuntimeError):
    def __init__(self, failures: list[tuple[str, str]]) -> None:
        summary = "; ".join(f"{name}: {reason}" for name, reason in failures) or "no provider is enabled and configured"
        super().__init__(f"All AI providers failed ({summary})")
        self.failures = failures


@runtime_checkable
class AIProvider(Protocol):
    name: str
    experimental: bool

    def is_ready(self) -> bool: ...

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int,
    ) -> AIResult: ...

    async def health(self) -> ProviderHealth: ...


@runtime_checkable
class StreamingAIProvider(AIProvider, Protocol):
    def stream(self, messages: list[ChatMessage], *, max_tokens: int) -> AsyncIterator[str]: ...


def split_system(messages: list[ChatMessage]) -> tuple[str | None, list[ChatMessage]]:
    system_parts = [message["content"] for message in messages if message["role"] == "system"]
    rest = [message for message in messages if message["role"] != "system"]
    return ("\n\n".join(system_parts) if system_parts else None), rest


def flatten_messages(messages: list[ChatMessage]) -> str:
    return "\n\n".join(message["content"] for message in messages)


def schema_instruction(json_schema: dict[str, Any]) -> str:
    return (
        "Respond with a single JSON object only, no prose and no code fences. "
        f"It must match this JSON Schema: {json.dumps(json_schema, ensure_ascii=False, sort_keys=True)}"
    )


def with_schema_instruction(messages: list[ChatMessage], json_schema: dict[str, Any]) -> list[ChatMessage]:
    return [{"role": "system", "content": schema_instruction(json_schema)}, *messages]


_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def parse_json_reply(provider_name: str, text: str) -> Any:
    candidate = text.strip()
    fenced = _FENCE_PATTERN.match(candidate)
    if fenced:
        candidate = fenced.group(1)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise ProviderBadResponse(provider_name, f"reply is not valid JSON: {exc}") from exc


def health_from_error(provider_name: str, error: ProviderError) -> ProviderHealth:
    if isinstance(error, ProviderAuthError):
        return ProviderHealth(provider_name, "auth_error", str(error))
    if isinstance(error, ProviderRateLimited):
        return ProviderHealth(provider_name, "rate_limited", str(error))
    return ProviderHealth(provider_name, "unavailable", str(error))
