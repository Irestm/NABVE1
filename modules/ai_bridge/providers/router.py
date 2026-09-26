from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any, cast

from core.logger import get_logger
from modules.ai_bridge.providers.anthropic_api import AnthropicApiProvider
from modules.ai_bridge.providers.base import (
    AIProvider,
    AIResult,
    AllProvidersFailed,
    ChainKind,
    ChatMessage,
    ProviderError,
    ProviderHealth,
    StreamingAIProvider,
)
from modules.ai_bridge.providers.config import ProvidersConfig, load_config
from modules.ai_bridge.providers.deepseek_api import DeepSeekApiProvider
from modules.ai_bridge.providers.experimental.browser_chain import BrowserChainProvider
from modules.ai_bridge.providers.gemini_api import GeminiApiProvider
from modules.ai_bridge.providers.groq_api import GroqApiProvider
from modules.ai_bridge.providers.ollama import OllamaProvider
from modules.ai_bridge.providers.openai_api import OpenAIApiProvider
from modules.ai_bridge.system_prompt import persona_instruction

logger = get_logger(__name__)

DEFAULT_MAX_TOKENS = 1024
_HEALTH_TIMEOUT_SECONDS = 20.0

ProviderFactory = Callable[[str | None], AIProvider]


def _with_model(provider_class: Callable[..., AIProvider]) -> ProviderFactory:
    def build(model: str | None) -> AIProvider:
        return provider_class(model) if model else provider_class()

    return build


PROVIDER_FACTORIES: dict[str, ProviderFactory] = {
    "ollama": lambda model: OllamaProvider(),
    "anthropic_api": _with_model(AnthropicApiProvider),
    "openai_api": _with_model(OpenAIApiProvider),
    "gemini_api": _with_model(GeminiApiProvider),
    "deepseek_api": _with_model(DeepSeekApiProvider),
    "groq_api": _with_model(GroqApiProvider),
    "browser_chain": lambda model: BrowserChainProvider(),
}

_CLAUDE_BY_CONNECTION: dict[str, str] = {"api_key": "anthropic_api", "subscription": "anthropic_subscription"}


class PromptPort:
    def __init__(self, provider: AIProvider) -> None:
        self._provider = provider
        self.name = provider.name

    def _messages(self, text: str) -> list[ChatMessage]:
        return [{"role": "system", "content": persona_instruction()}, {"role": "user", "content": text}]

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
        result = await self._provider.complete(self._messages(text), max_tokens=DEFAULT_MAX_TOKENS)
        return result.text


class StreamingPromptPort(PromptPort):
    async def stream_prompt(self, text: str) -> AsyncIterator[str]:
        provider = cast(StreamingAIProvider, self._provider)
        async for delta in provider.stream(self._messages(text), max_tokens=DEFAULT_MAX_TOKENS):
            yield delta


class ProviderRouter:
    def __init__(
        self,
        config_loader: Callable[[], ProvidersConfig] = load_config,
        factories: dict[str, ProviderFactory] | None = None,
    ) -> None:
        self._config_loader = config_loader
        self._factories = factories if factories is not None else PROVIDER_FACTORIES
        self._instances: dict[str, tuple[str | None, AIProvider]] = {}

    def config(self) -> ProvidersConfig:
        return self._config_loader()

    def known_providers(self) -> list[str]:
        return list(self._factories)

    def provider(self, name: str, config: ProvidersConfig | None = None) -> AIProvider | None:
        factory = self._factories.get(name)
        if factory is None:
            return None
        model = (config or self.config()).models.get(name)
        cached = self._instances.get(name)
        if cached is not None and cached[0] == model:
            return cached[1]
        instance = factory(model)
        self._instances[name] = (model, instance)
        return instance

    def _is_selected(self, name: str, config: ProvidersConfig) -> bool:
        if not config.is_enabled(name):
            return False
        if name in _CLAUDE_BY_CONNECTION.values():
            return _CLAUDE_BY_CONNECTION[config.claude_connection] == name
        return True

    def chain(self, kind: ChainKind = "default") -> list[AIProvider]:
        config = self.config()
        selected: list[AIProvider] = []
        for name in config.chains.get(kind, []):
            if not self._is_selected(name, config):
                continue
            provider = self.provider(name, config)
            if provider is None:
                continue
            try:
                ready = provider.is_ready()
            except Exception:
                logger.exception("Provider '%s' readiness check failed; skipping it", name)
                continue
            if ready:
                selected.append(provider)
        return selected

    def ports(self, kind: ChainKind = "default") -> list[PromptPort]:
        return self.ports_of(self.chain(kind))

    def ports_of(self, providers: list[AIProvider]) -> list[PromptPort]:
        return [
            StreamingPromptPort(provider) if isinstance(provider, StreamingAIProvider) else PromptPort(provider)
            for provider in providers
        ]

    async def ask(self, text: str, *, kind: ChainKind = "default", max_tokens: int = DEFAULT_MAX_TOKENS) -> AIResult:
        messages: list[ChatMessage] = [
            {"role": "system", "content": persona_instruction()},
            {"role": "user", "content": text},
        ]
        return await self.complete(messages, max_tokens=max_tokens, kind=kind)

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        kind: ChainKind = "default",
    ) -> AIResult:
        providers = self.chain(kind)
        failures: list[tuple[str, str]] = []
        for index, provider in enumerate(providers):
            try:
                return await provider.complete(messages, json_schema=json_schema, max_tokens=max_tokens)
            except ProviderError as exc:
                reason = f"{type(exc).__name__}: {exc}"
            except Exception as exc:
                logger.exception("Provider '%s' raised an unexpected error", provider.name)
                reason = f"{type(exc).__name__}: {exc}"
            failures.append((provider.name, reason))
            next_name = providers[index + 1].name if index + 1 < len(providers) else None
            if next_name is None:
                logger.warning("Provider '%s' failed (%s); no providers left in '%s' chain", provider.name, reason, kind)
            else:
                logger.warning("Provider '%s' failed (%s); switching to '%s'", provider.name, reason, next_name)
        raise AllProvidersFailed(failures)

    async def health_all(self) -> list[ProviderHealth]:
        config = self.config()
        names = self.known_providers()
        return list(await asyncio.gather(*(self._health_of(name, config) for name in names)))

    async def _health_of(self, name: str, config: ProvidersConfig) -> ProviderHealth:
        provider = self.provider(name, config)
        if provider is None:
            return ProviderHealth(name, "unavailable", "неизвестный провайдер")
        if not config.is_enabled(name):
            return ProviderHealth(name, "disabled", None, experimental=provider.experimental)
        try:
            health = await asyncio.wait_for(provider.health(), timeout=_HEALTH_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            return ProviderHealth(name, "unavailable", "проверка не уложилась в таймаут", experimental=provider.experimental)
        except Exception as exc:
            logger.exception("Health check for provider '%s' failed", name)
            return ProviderHealth(name, "unavailable", str(exc), experimental=provider.experimental)
        return health


_router: ProviderRouter | None = None


def get_router() -> ProviderRouter:
    global _router
    if _router is None:
        _router = ProviderRouter()
    return _router
