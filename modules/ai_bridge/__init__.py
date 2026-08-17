from __future__ import annotations

from typing import Any

from core.dispatcher import CommandDispatcher
from core.logger import get_logger
from modules.ai_bridge import provider_auth
from modules.ai_bridge.presets import PRESET_PROMPTS
from modules.ai_bridge.provider_manager import get_provider_manager

logger = get_logger(__name__)


def _build_prompt(params: dict[str, Any]) -> str:
    preset_id = params.get("preset_id")
    prompt = params.get("prompt")

    if preset_id:
        template = PRESET_PROMPTS.get(preset_id)
        if template is None:
            raise ValueError(f"Unknown preset_id '{preset_id}'")
        return template.format(input=prompt or "")

    if prompt:
        return prompt

    raise ValueError("Either 'prompt' or a valid 'preset_id' must be provided")


async def _handle_ai_bridge_ask(params: dict[str, Any]) -> dict[str, Any]:
    text = _build_prompt(params)
    manager = get_provider_manager()
    reply = await manager.send_prompt(text, fast_mode=bool(params.get("fast_mode", False)))
    return {"response": reply, "provider": manager.active_name}


async def _handle_ai_bridge_show_provider(_params: dict[str, Any]) -> dict[str, Any]:
    manager = get_provider_manager()
    await manager.reveal_active()
    return {"provider": manager.active_name}


async def _handle_ai_bridge_hide_provider(_params: dict[str, Any]) -> dict[str, Any]:
    manager = get_provider_manager()
    await manager.hide_active()
    return {"provider": manager.active_name}


def _require_provider(params: dict[str, Any]) -> str:
    provider = params.get("provider")
    if not provider:
        raise ValueError("Missing required parameter 'provider'")
    return str(provider)


async def _handle_ai_bridge_provider_login(params: dict[str, Any]) -> dict[str, Any]:
    provider = _require_provider(params)
    await provider_auth.login(provider)
    return {"provider": provider, "message": "Открываю окно входа — авторизуйтесь на сайте провайдера сами."}


async def _handle_ai_bridge_provider_logout(params: dict[str, Any]) -> dict[str, Any]:
    provider = _require_provider(params)
    await provider_auth.logout(provider)
    return {"provider": provider}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "ai_bridge_ask",
        _handle_ai_bridge_ask,
        dangerous=False,
        description=(
            "Ask the currently active AI provider (Gemini, falling back to ChatGPT, "
            "DeepSeek, then Grok when a daily limit is hit) a fixed preset prompt or "
            "free-text prompt (prompt, or preset_id), via browser automation."
        ),
    )
    dispatcher.register(
        "ai_bridge_show_provider",
        _handle_ai_bridge_show_provider,
        dangerous=False,
        description="Bring the active AI provider's background browser tab to the foreground.",
    )
    dispatcher.register(
        "ai_bridge_hide_provider",
        _handle_ai_bridge_hide_provider,
        dangerous=False,
        description="Send the active AI provider's browser tab back to the background.",
    )
    dispatcher.register(
        "ai_bridge_provider_login",
        _handle_ai_bridge_provider_login,
        dangerous=False,
        description=(
            "Open a visible browser window on the given AI provider's own login page (provider: "
            "gemini/chatgpt/deepseek/grok) so the user can log in themselves — never asks for or "
            "stores the password."
        ),
    )
    dispatcher.register(
        "ai_bridge_provider_logout",
        _handle_ai_bridge_provider_logout,
        dangerous=False,
        description="Reset an AI provider's browser session back to guest (provider).",
    )
