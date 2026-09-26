from __future__ import annotations

from typing import Any

from modules.ai_bridge.providers.base import (
    AIResult,
    ChatMessage,
    ProviderHealth,
    ProviderRateLimited,
    ProviderUnavailable,
    flatten_messages,
    parse_json_reply,
    with_schema_instruction,
)
from modules.ai_bridge.providers.experimental.provider_manager import (
    AllProvidersExhaustedError,
    get_provider_manager,
)

RISK_WARNING = (
    "Экспериментально: управление веб-интерфейсами Gemini/ChatGPT/DeepSeek/Grok через браузер. "
    "На свой риск — может нарушать условия использования этих сервисов."
)


class BrowserChainProvider:
    name = "browser_chain"
    experimental = True

    def is_ready(self) -> bool:
        return True

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int,
    ) -> AIResult:
        prepared = with_schema_instruction(messages, json_schema) if json_schema is not None else messages
        try:
            text = await get_provider_manager().send_raw(flatten_messages(prepared), fast_mode=True)
        except AllProvidersExhaustedError as exc:
            raise ProviderRateLimited(self.name, str(exc)) from exc
        except Exception as exc:
            raise ProviderUnavailable(self.name, str(exc)) from exc
        return AIResult(
            text=text,
            provider_name=self.name,
            parsed_json=parse_json_reply(self.name, text) if json_schema is not None else None,
        )

    async def health(self) -> ProviderHealth:
        status = get_provider_manager().status()
        return ProviderHealth(
            self.name,
            "ok",
            f"активный: {status['active_provider']}",
            experimental=True,
            extra={"warning": RISK_WARNING, **status},
        )
