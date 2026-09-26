from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from modules.ai_bridge.providers import anthropic_subscription as module
from modules.ai_bridge.providers.anthropic_subscription import AnthropicSubscriptionProvider, CliOutput
from modules.ai_bridge.providers.base import (
    ProviderAuthError,
    ProviderBadResponse,
    ProviderRateLimited,
    ProviderUnavailable,
)

_MESSAGES: list[Any] = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "вопрос"}]


class _Runner:
    def __init__(self, payload: Any = None, *, returncode: int = 0, stderr: bytes = b"", error: Exception | None = None) -> None:
        self.payload = payload
        self.returncode = returncode
        self.stderr = stderr
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, command: list[str], stdin: bytes, env: dict[str, str], cwd: Path, timeout: float) -> CliOutput:
        self.calls.append({"command": command, "stdin": stdin, "env": env, "cwd": cwd})
        if self.error is not None:
            raise self.error
        stdout = self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode()
        return CliOutput(self.returncode, stdout, self.stderr)


def _ok(result: str, structured: Any = None) -> dict[str, Any]:
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": result,
        "structured_output": structured,
        "api_error_status": None,
        "usage": {"input_tokens": 12, "output_tokens": 3},
    }


@pytest.fixture(autouse=True)
def _cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(module, "find_cli", lambda: "/usr/bin/claude")
    monkeypatch.setattr(module, "WORKDIR", tmp_path / "cli")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-should-not-leak")


def test_builds_headless_command_and_hides_api_credentials() -> None:
    runner = _Runner(_ok("ответ"))

    result = asyncio.run(AnthropicSubscriptionProvider("sonnet", runner).complete(_MESSAGES, max_tokens=100))

    call = runner.calls[0]
    command = call["command"]
    assert command[:4] == ["/usr/bin/claude", "-p", "--output-format", "json"]
    assert command[command.index("--tools") + 1] == ""
    assert "--no-session-persistence" in command and "--strict-mcp-config" in command
    assert command[command.index("--system-prompt") + 1] == "SYS"
    assert command[command.index("--model") + 1] == "sonnet"
    assert call["stdin"] == "вопрос".encode()
    assert "ANTHROPIC_API_KEY" not in call["env"] and "ANTHROPIC_AUTH_TOKEN" not in call["env"]
    assert result.text == "ответ" and result.usage == {"input_tokens": 12, "output_tokens": 3}


def test_json_schema_uses_structured_output() -> None:
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}}
    runner = _Runner(_ok("", {"a": 1}))

    result = asyncio.run(AnthropicSubscriptionProvider(runner=runner).complete(_MESSAGES, json_schema=schema, max_tokens=10))

    command = runner.calls[0]["command"]
    assert json.loads(command[command.index("--json-schema") + 1]) == schema
    assert result.parsed_json == {"a": 1}
    assert json.loads(result.text) == {"a": 1}


def test_json_schema_falls_back_to_parsing_text() -> None:
    runner = _Runner(_ok('{"a": 2}'))

    result = asyncio.run(AnthropicSubscriptionProvider(runner=runner).complete(_MESSAGES, json_schema={}, max_tokens=10))

    assert result.parsed_json == {"a": 2}


def test_multi_turn_conversation_is_flattened() -> None:
    runner = _Runner(_ok("ok"))
    messages: list[Any] = [
        {"role": "user", "content": "привет"},
        {"role": "assistant", "content": "здравствуй"},
        {"role": "user", "content": "как дела?"},
    ]

    asyncio.run(AnthropicSubscriptionProvider(runner=runner).complete(messages, max_tokens=10))

    assert runner.calls[0]["stdin"].decode() == "User: привет\n\nAssistant: здравствуй\n\nUser: как дела?"
    assert "--system-prompt" not in runner.calls[0]["command"]


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({**_ok("Claude usage limit reached. Your limit will reset at 5pm"), "is_error": True}, ProviderRateLimited),
        ({**_ok("API Error"), "is_error": True, "api_error_status": 429}, ProviderRateLimited),
        ({**_ok("Invalid API key · Please run /login"), "is_error": True}, ProviderAuthError),
        ({**_ok("Something broke"), "is_error": True, "subtype": "error_during_execution"}, ProviderUnavailable),
    ],
)
def test_errors_are_mapped(payload: dict[str, Any], expected: type) -> None:
    with pytest.raises(expected):
        asyncio.run(AnthropicSubscriptionProvider(runner=_Runner(payload)).complete(_MESSAGES, max_tokens=10))


def test_non_json_output_uses_stderr_for_mapping() -> None:
    runner = _Runner(b"", returncode=1, stderr=b"Error: not logged in")

    with pytest.raises(ProviderAuthError):
        asyncio.run(AnthropicSubscriptionProvider(runner=runner).complete(_MESSAGES, max_tokens=10))


def test_empty_reply_is_bad_response() -> None:
    with pytest.raises(ProviderBadResponse):
        asyncio.run(AnthropicSubscriptionProvider(runner=_Runner(_ok("  "))).complete(_MESSAGES, max_tokens=10))


def test_timeout_and_missing_binary_are_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ProviderUnavailable):
        asyncio.run(
            AnthropicSubscriptionProvider(runner=_Runner(error=asyncio.TimeoutError())).complete(_MESSAGES, max_tokens=10)
        )
    monkeypatch.setattr(module, "find_cli", lambda: None)
    provider = AnthropicSubscriptionProvider(runner=_Runner(_ok("x")))
    assert provider.is_ready() is False
    with pytest.raises(ProviderUnavailable):
        asyncio.run(provider.complete(_MESSAGES, max_tokens=10))
    assert asyncio.run(provider.health()).status == "not_configured"


def test_health_runs_a_test_request_and_caches_it() -> None:
    runner = _Runner(_ok("OK"))
    provider = AnthropicSubscriptionProvider(runner=runner)

    first = asyncio.run(provider.health())
    second = asyncio.run(provider.health())

    assert first.status == second.status == "ok"
    assert len(runner.calls) == 1


def test_health_reports_auth_problems() -> None:
    runner = _Runner({**_ok("Please run /login"), "is_error": True})

    assert asyncio.run(AnthropicSubscriptionProvider(runner=runner).health()).status == "auth_error"


def test_run_cli_executes_a_real_process(tmp_path: Path) -> None:
    output = asyncio.run(module.run_cli(["cat"], b"echo", {"PATH": "/usr/bin:/bin"}, tmp_path, 10))

    assert output.returncode == 0 and output.stdout == b"echo"


def test_run_cli_kills_on_timeout(tmp_path: Path) -> None:
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(module.run_cli(["sleep", "5"], b"", {"PATH": "/usr/bin:/bin"}, tmp_path, 0.2))
