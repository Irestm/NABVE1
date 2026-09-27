from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable, Iterable
from typing import Any

from core.logger import get_logger
from modules.ai_bridge.providers.base import AllProvidersFailed, ChatMessage, ProviderError, StreamingAIProvider
from modules.ai_bridge.providers.router import ProviderRouter, get_router

logger = get_logger(__name__)

MASK = "•••"
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
KNOWN_ACTIONS: frozenset[str] = frozenset({"difficulty_check", "set_level"})

StreamFn = Callable[[list[ChatMessage], int], AsyncIterator[str]]


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_reply(
    messages: list[ChatMessage], max_tokens: int, router: ProviderRouter | None = None
) -> AsyncIterator[str]:
    active = router or get_router()
    failures: list[tuple[str, str]] = []
    for provider in active.chain("default"):
        started = False
        try:
            if isinstance(provider, StreamingAIProvider):
                async for delta in provider.stream(messages, max_tokens=max_tokens):
                    started = True
                    yield delta
            else:
                result = await provider.complete(messages, max_tokens=max_tokens)
                started = True
                yield result.text
            return
        except ProviderError as exc:
            if started:
                raise
            failures.append((provider.name, f"{type(exc).__name__}: {exc}"))
            logger.warning("Assistant provider '%s' failed before answering: %s", provider.name, exc)
        except Exception as exc:
            if started:
                raise
            logger.exception("Assistant provider '%s' raised an unexpected error", provider.name)
            failures.append((provider.name, f"{type(exc).__name__}: {exc}"))
    raise AllProvidersFailed(failures)


def _term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term.strip())
    escaped = escaped.replace("е", "[её]").replace("ё", "[её]").replace("Е", "[ЕЁ]").replace("Ё", "[ЕЁ]")
    escaped = re.sub(r"(\\ )+", r"\\s+", escaped)
    return re.compile(rf"(?<![\wё]){escaped}(?![\wё])", re.IGNORECASE)


class AnswerGuard:
    def __init__(self, forbidden: Iterable[str]) -> None:
        terms = sorted({term.strip() for term in forbidden if len(term.strip()) >= 2}, key=len, reverse=True)
        self._patterns = [_term_pattern(term) for term in terms]
        self._hold = max((len(term) for term in terms), default=0) + 1 if terms else 0
        self._buffer = ""
        self.masked = False

    def _mask(self, text: str) -> str:
        for pattern in self._patterns:
            text, count = pattern.subn(MASK, text)
            if count:
                self.masked = True
        return text

    def feed(self, chunk: str) -> str:
        if not self._patterns:
            return chunk
        self._buffer = self._mask(self._buffer + chunk)
        if len(self._buffer) <= self._hold:
            return ""
        ready, self._buffer = self._buffer[: -self._hold], self._buffer[-self._hold :]
        return ready

    def flush(self) -> str:
        if not self._patterns:
            return ""
        out, self._buffer = self._mask(self._buffer), ""
        return out


def parse_action(text: str) -> dict[str, Any] | None:
    stripped = _FENCE.sub("", text.strip()).strip()
    if not stripped.startswith("{"):
        return None
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
    if isinstance(data, dict) and data.get("action") in KNOWN_ACTIONS:
        return data
    return None


def looks_like_json(prefix: str) -> bool | None:
    stripped = prefix.lstrip()
    if not stripped:
        return None
    return stripped[0] in "{`"
