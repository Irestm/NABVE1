from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import openai
import pytest
from google.genai import errors as genai_errors

from modules.ai_bridge.providers import anthropic_api, gemini_api, keys, openai_compatible
from modules.ai_bridge.providers.anthropic_api import AnthropicApiProvider
from modules.ai_bridge.providers.base import (
    ProviderAuthError,
    ProviderBadResponse,
    ProviderRateLimited,
    ProviderUnavailable,
)
from modules.ai_bridge.providers.deepseek_api import DeepSeekApiProvider
from modules.ai_bridge.providers.gemini_api import GeminiApiProvider
from modules.ai_bridge.providers.groq_api import GroqApiProvider
from modules.ai_bridge.providers.openai_api import OpenAIApiProvider
from modules.ai_bridge.quota_tracker import QuotaTracker
from modules.ai_bridge.state_store import StateStore

_REQUEST = httpx2.Request("POST", "https://example.invalid/v1")
_MESSAGES: list[Any] = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "вопрос"}]


def _response(status: int) -> httpx2.Response:
    return httpx2.Response(status, request=_REQUEST)


@pytest.fixture(autouse=True)
def _fake_keys(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    stored = {name: f"{name}-key" for name in keys.KEY_SPECS}
    for module in (anthropic_api, gemini_api, openai_compatible):
        monkeypatch.setattr(module, "read_key", lambda name: stored.get(name))
    return stored


class _Recorder:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.kwargs: dict[str, Any] = {}

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return self.result


def _anthropic_message(text: str, stop_reason: str = "end_turn") -> Any:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=11, output_tokens=7),
    )


def _install_anthropic(monkeypatch: pytest.MonkeyPatch, provider: AnthropicApiProvider, create: _Recorder) -> None:
    client = SimpleNamespace(messages=SimpleNamespace(create=create), models=SimpleNamespace(retrieve=create))
    monkeypatch.setattr(provider, "_client_for_current_key", lambda: client)


def test_anthropic_sends_system_separately_and_returns_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = AnthropicApiProvider("claude-test")
    create = _Recorder(_anthropic_message("ответ"))
    _install_anthropic(monkeypatch, provider, create)

    result = asyncio.run(provider.complete(_MESSAGES, max_tokens=100))

    assert result.text == "ответ"
    assert result.usage == {"input_tokens": 11, "output_tokens": 7}
    assert create.kwargs["system"] == "SYS"
    assert create.kwargs["messages"] == [{"role": "user", "content": "вопрос"}]
    assert create.kwargs["model"] == "claude-test"
    assert "output_config" not in create.kwargs


def test_anthropic_structured_output_uses_output_config(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = AnthropicApiProvider()
    create = _Recorder(_anthropic_message('{"word": "cat"}'))
    _install_anthropic(monkeypatch, provider, create)
    schema = {"type": "object", "properties": {"word": {"type": "string"}}}

    result = asyncio.run(provider.complete(_MESSAGES, json_schema=schema, max_tokens=100))

    assert result.parsed_json == {"word": "cat"}
    assert create.kwargs["output_config"] == {"format": {"type": "json_schema", "schema": schema}}


def test_anthropic_refusal_is_a_bad_response(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = AnthropicApiProvider()
    _install_anthropic(monkeypatch, provider, _Recorder(_anthropic_message("", stop_reason="refusal")))

    with pytest.raises(ProviderBadResponse):
        asyncio.run(provider.complete(_MESSAGES, max_tokens=100))


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (anthropic.RateLimitError("limit", response=_response(429), body=None), ProviderRateLimited),
        (anthropic.AuthenticationError("bad", response=_response(401), body=None), ProviderAuthError),
        (anthropic.PermissionDeniedError("no", response=_response(403), body=None), ProviderAuthError),
        (anthropic.InternalServerError("oops", response=_response(500), body=None), ProviderUnavailable),
        (anthropic.APIConnectionError(request=_REQUEST), ProviderUnavailable),
        (anthropic.BadRequestError("bad request", response=_response(400), body=None), ProviderBadResponse),
    ],
)
def test_anthropic_errors_are_mapped(monkeypatch: pytest.MonkeyPatch, error: Exception, expected: type) -> None:
    provider = AnthropicApiProvider()
    _install_anthropic(monkeypatch, provider, _Recorder(error=error))

    with pytest.raises(expected):
        asyncio.run(provider.complete(_MESSAGES, max_tokens=100))


def test_anthropic_without_key_is_not_ready_and_reports_not_configured(
    monkeypatch: pytest.MonkeyPatch, _fake_keys: dict[str, str]
) -> None:
    del _fake_keys["anthropic_api"]
    provider = AnthropicApiProvider()

    assert provider.is_ready() is False
    assert asyncio.run(provider.health()).status == "not_configured"
    with pytest.raises(ProviderAuthError):
        asyncio.run(provider.complete(_MESSAGES, max_tokens=100))


def test_anthropic_health_maps_auth_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = AnthropicApiProvider()
    _install_anthropic(
        monkeypatch, provider, _Recorder(error=anthropic.AuthenticationError("bad", response=_response(401), body=None))
    )

    assert asyncio.run(provider.health()).status == "auth_error"


def _openai_completion(text: str | None) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3),
    )


def _install_openai(monkeypatch: pytest.MonkeyPatch, provider: Any, create: _Recorder) -> None:
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        models=SimpleNamespace(retrieve=create),
    )
    monkeypatch.setattr(provider, "_client_for_current_key", lambda: client)


def test_openai_uses_strict_json_schema_and_max_completion_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenAIApiProvider("gpt-test")
    create = _Recorder(_openai_completion('{"a": 1}'))
    _install_openai(monkeypatch, provider, create)

    result = asyncio.run(provider.complete(_MESSAGES, json_schema={"type": "object"}, max_tokens=50))

    assert result.parsed_json == {"a": 1}
    assert result.usage == {"input_tokens": 5, "output_tokens": 3}
    assert create.kwargs["max_completion_tokens"] == 50
    assert create.kwargs["response_format"]["type"] == "json_schema"
    assert create.kwargs["response_format"]["json_schema"]["strict"] is True
    assert create.kwargs["messages"][0] == {"role": "system", "content": "SYS"}


def test_deepseek_uses_json_object_mode_with_schema_instruction(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = DeepSeekApiProvider()
    create = _Recorder(_openai_completion('{"a": 2}'))
    _install_openai(monkeypatch, provider, create)

    result = asyncio.run(provider.complete(_MESSAGES, json_schema={"type": "object"}, max_tokens=50))

    assert result.parsed_json == {"a": 2}
    assert create.kwargs["response_format"] == {"type": "json_object"}
    assert create.kwargs["max_tokens"] == 50
    assert "JSON Schema" in create.kwargs["messages"][0]["content"]


def test_openai_empty_reply_is_a_bad_response(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenAIApiProvider()
    _install_openai(monkeypatch, provider, _Recorder(_openai_completion(None)))

    with pytest.raises(ProviderBadResponse):
        asyncio.run(provider.complete(_MESSAGES, max_tokens=50))


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (openai.RateLimitError("limit", response=_response(429), body=None), ProviderRateLimited),
        (openai.AuthenticationError("bad", response=_response(401), body=None), ProviderAuthError),
        (openai.APIStatusError("no money", response=_response(402), body=None), ProviderRateLimited),
        (openai.InternalServerError("oops", response=_response(503), body=None), ProviderUnavailable),
        (openai.APIConnectionError(request=_REQUEST), ProviderUnavailable),
    ],
)
def test_openai_compatible_errors_are_mapped(monkeypatch: pytest.MonkeyPatch, error: Exception, expected: type) -> None:
    provider = DeepSeekApiProvider()
    _install_openai(monkeypatch, provider, _Recorder(error=error))

    with pytest.raises(expected):
        asyncio.run(provider.complete(_MESSAGES, max_tokens=50))


def test_groq_is_not_ready_near_its_per_minute_quota(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    quota = QuotaTracker(daily_store=StateStore(db_path=tmp_path / "q.db"))
    provider = GroqApiProvider(quota=quota)
    create = _Recorder(_openai_completion("ok"))
    _install_openai(monkeypatch, provider, create)

    assert provider.is_ready() is True
    for _ in range(40):
        asyncio.run(provider.complete(_MESSAGES, max_tokens=10))

    assert provider.is_ready() is False


def _gemini_response(text: str) -> Any:
    return SimpleNamespace(text=text, usage_metadata=SimpleNamespace(prompt_token_count=4, candidates_token_count=2))


def _install_gemini(monkeypatch: pytest.MonkeyPatch, provider: GeminiApiProvider, call: _Recorder) -> None:
    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=call, get=call)))
    monkeypatch.setattr(provider, "_client_for_current_key", lambda: client)


def test_gemini_maps_roles_system_and_json_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    provider = GeminiApiProvider("gemini-test", QuotaTracker(daily_store=StateStore(db_path=tmp_path / "q.db")))
    call = _Recorder(_gemini_response('{"a": 3}'))
    _install_gemini(monkeypatch, provider, call)
    messages: list[Any] = [*_MESSAGES, {"role": "assistant", "content": "раньше"}]

    result = asyncio.run(provider.complete(messages, json_schema={"type": "object"}, max_tokens=64))

    assert result.parsed_json == {"a": 3}
    assert result.usage == {"input_tokens": 4, "output_tokens": 2}
    assert [content.role for content in call.kwargs["contents"]] == ["user", "model"]
    config = call.kwargs["config"]
    assert config.system_instruction == "SYS"
    assert config.max_output_tokens == 64
    assert config.response_mime_type == "application/json"
    assert provider.requests_used_today() == 1


@pytest.mark.parametrize(
    ("code", "expected"),
    [(429, ProviderRateLimited), (403, ProviderAuthError), (503, ProviderUnavailable), (400, ProviderBadResponse)],
)
def test_gemini_errors_are_mapped(monkeypatch: pytest.MonkeyPatch, tmp_path: Any, code: int, expected: type) -> None:
    provider = GeminiApiProvider(quota=QuotaTracker(daily_store=StateStore(db_path=tmp_path / "q.db")))
    _install_gemini(monkeypatch, provider, _Recorder(error=genai_errors.APIError(code, {"error": {"message": "x"}})))

    with pytest.raises(expected):
        asyncio.run(provider.complete(_MESSAGES, max_tokens=64))
