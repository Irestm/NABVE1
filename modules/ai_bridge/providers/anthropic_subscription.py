from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.config import DATA_DIR
from core.logger import get_logger
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

logger = get_logger(__name__)

CLI_NAME = "claude"
CLI_FALLBACK_PATHS: tuple[Path, ...] = (
    Path.home() / ".local" / "bin" / "claude",
    Path.home() / ".claude" / "local" / "claude",
)
WORKDIR: Path = DATA_DIR / "claude_cli_workdir"
TIMEOUT_SECONDS = 120.0
HEALTH_CACHE_SECONDS = 600.0
_STRIPPED_ENV: frozenset[str] = frozenset({"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"})
_RATE_LIMIT_MARKERS: tuple[str, ...] = ("rate limit", "usage limit", "limit reached", "limit will reset", "429")
_AUTH_MARKERS: tuple[str, ...] = ("login", "log in", "not logged", "authentication", "invalid api key", "401", "403")


@dataclass(frozen=True)
class CliOutput:
    returncode: int
    stdout: bytes
    stderr: bytes


Runner = Callable[[list[str], bytes, dict[str, str], Path, float], Awaitable[CliOutput]]


async def run_cli(command: list[str], stdin: bytes, env: dict[str, str], cwd: Path, timeout: float) -> CliOutput:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=cwd,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(stdin), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise
    return CliOutput(returncode=process.returncode or 0, stdout=stdout, stderr=stderr)


def find_cli() -> str | None:
    found = shutil.which(CLI_NAME)
    if found:
        return found
    return next((str(path) for path in CLI_FALLBACK_PATHS if path.is_file() and os.access(path, os.X_OK)), None)


def _child_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in _STRIPPED_ENV}


def _prompt_text(conversation: list[ChatMessage]) -> str:
    if len(conversation) == 1:
        return conversation[0]["content"]
    labels = {"user": "User", "assistant": "Assistant", "system": "System"}
    return "\n\n".join(f"{labels[message['role']]}: {message['content']}" for message in conversation)


def map_cli_error(provider_name: str, text: str, api_status: Any) -> ProviderError:
    lowered = text.lower()
    if api_status == 429 or any(marker in lowered for marker in _RATE_LIMIT_MARKERS):
        return ProviderRateLimited(provider_name, "лимит подписки исчерпан")
    if api_status in (401, 403) or any(marker in lowered for marker in _AUTH_MARKERS):
        return ProviderAuthError(provider_name, "Claude CLI не авторизован — выполните `claude` и войдите")
    return ProviderUnavailable(provider_name, text.strip()[:300] or "Claude CLI завершился с ошибкой")


class AnthropicSubscriptionProvider:
    name = "anthropic_subscription"
    experimental = False

    def __init__(self, model: str | None = None, runner: Runner = run_cli) -> None:
        self._model = model
        self._runner = runner
        self._health_cache: tuple[float, ProviderHealth] | None = None

    def is_ready(self) -> bool:
        return find_cli() is not None

    def _command(self, cli: str, system: str | None, json_schema: dict[str, Any] | None) -> list[str]:
        command = [
            cli,
            "-p",
            "--output-format",
            "json",
            "--tools",
            "",
            "--strict-mcp-config",
            "--no-session-persistence",
        ]
        if system:
            command += ["--system-prompt", system]
        if json_schema is not None:
            command += ["--json-schema", json.dumps(json_schema, ensure_ascii=False)]
        if self._model:
            command += ["--model", self._model]
        return command

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int,
    ) -> AIResult:
        cli = find_cli()
        if cli is None:
            raise ProviderUnavailable(self.name, "Claude CLI не установлен")
        system, conversation = split_system(messages)
        if not conversation:
            raise ProviderBadResponse(self.name, "пустой запрос")
        WORKDIR.mkdir(parents=True, exist_ok=True)
        try:
            output = await self._runner(
                self._command(cli, system, json_schema),
                _prompt_text(conversation).encode("utf-8"),
                _child_env(),
                WORKDIR,
                TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise ProviderUnavailable(self.name, f"Claude CLI не ответил за {TIMEOUT_SECONDS:.0f} с") from exc
        except OSError as exc:
            raise ProviderUnavailable(self.name, f"не удалось запустить Claude CLI: {exc}") from exc
        return self._parse(output, json_schema)

    def _parse(self, output: CliOutput, json_schema: dict[str, Any] | None) -> AIResult:
        stdout = output.stdout.decode("utf-8", errors="replace").strip()
        stderr = output.stderr.decode("utf-8", errors="replace")
        try:
            payload = json.loads(stdout.splitlines()[-1]) if stdout else None
        except json.JSONDecodeError:
            payload = None
        if not isinstance(payload, dict):
            raise map_cli_error(self.name, f"{stdout}\n{stderr}", None)
        text = str(payload.get("result") or "")
        if payload.get("is_error") or payload.get("subtype") not in (None, "success") or output.returncode != 0:
            raise map_cli_error(self.name, f"{text}\n{stderr}", payload.get("api_error_status"))
        structured = payload.get("structured_output")
        parsed: Any = None
        if json_schema is not None:
            parsed = structured if structured is not None else parse_json_reply(self.name, text)
            if not text:
                text = json.dumps(parsed, ensure_ascii=False)
        if not text.strip():
            raise ProviderBadResponse(self.name, "пустой ответ")
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        return AIResult(
            text=text,
            provider_name=self.name,
            parsed_json=parsed,
            usage={
                "input_tokens": int(usage.get("input_tokens") or 0),
                "output_tokens": int(usage.get("output_tokens") or 0),
            },
        )

    async def health(self) -> ProviderHealth:
        cli = find_cli()
        if cli is None:
            return ProviderHealth(self.name, "not_configured", "Claude CLI не установлен")
        cached = self._health_cache
        if cached is not None and time.monotonic() - cached[0] < HEALTH_CACHE_SECONDS:
            return cached[1]
        started = time.monotonic()
        try:
            await self.complete(
                [{"role": "system", "content": "Reply with the single word OK."}, {"role": "user", "content": "ping"}],
                max_tokens=16,
            )
        except ProviderError as exc:
            health = health_from_error(self.name, exc)
        else:
            health = ProviderHealth(self.name, "ok", cli, int((time.monotonic() - started) * 1000))
        self._health_cache = (time.monotonic(), health)
        return health
