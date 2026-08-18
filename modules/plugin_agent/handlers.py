from __future__ import annotations

import asyncio
from typing import Any

from core.dispatcher import CommandDispatcher
from core.logger import get_logger
from modules.plugin_agent import git_safety, service_layer
from modules.plugin_agent.domain import GapCandidate, GapCandidateStatus
from modules.plugin_agent.plugin_loader import (
    PLUGINS_DIR,
    get_registry,
    init_plugin_loader,
    start_hot_reload,
)
from modules.plugin_agent.plugin_generator import get_claude_auth_status, start_claude_login
from modules.plugin_agent.promotion_worker import GapPromotionWorker
from modules.plugin_agent.uow import PluginAgentUnitOfWork

logger = get_logger(__name__)

gap_promotion_worker = GapPromotionWorker()
_hot_reload_observer: Any = None


def _candidate_to_dict(candidate: GapCandidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "description": candidate.representative_text,
        "message": candidate.suggestion_message(),
        "status": candidate.status.value,
        "plugin_name": candidate.generated_plugin_name,
        "safety_flags": candidate.safety_flags,
        "requires_manual_review": bool(candidate.safety_flags),
        "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
        "last_seen": candidate.last_seen.isoformat() if candidate.last_seen else None,
    }


async def _handle_list_suggestions(_params: dict[str, Any]) -> dict[str, Any]:
    def _load() -> list[GapCandidate]:
        pending = service_layer.list_candidates(PluginAgentUnitOfWork(), GapCandidateStatus.PENDING_REVIEW)
        requires_review = service_layer.list_candidates(
            PluginAgentUnitOfWork(), GapCandidateStatus.REQUIRES_REVIEW
        )
        return [*pending, *requires_review]

    candidates = await asyncio.to_thread(_load)
    suggestions = [_candidate_to_dict(c) for c in candidates]
    suggestions.sort(key=lambda item: item["last_seen"] or "", reverse=True)
    return {"suggestions": suggestions}


async def _handle_get_code(params: dict[str, Any]) -> dict[str, Any]:
    suggestion_id = params.get("suggestion_id")
    if suggestion_id is None:
        raise ValueError("Не указан идентификатор предложения.")
    code = await asyncio.to_thread(service_layer.get_generated_code, PluginAgentUnitOfWork(), int(suggestion_id))
    return {"suggestion_id": suggestion_id, "code": code}


async def _handle_approve(params: dict[str, Any]) -> dict[str, Any]:
    suggestion_id = params.get("suggestion_id")
    if suggestion_id is None:
        raise ValueError("Не указан идентификатор предложения.")

    def _approve() -> tuple[str, Any]:
        return service_layer.approve(PluginAgentUnitOfWork(), int(suggestion_id), get_registry(), PLUGINS_DIR)

    enabled_command, destination = await asyncio.to_thread(_approve)
    await asyncio.to_thread(git_safety.commit_enabled_plugin, destination)
    return {"suggestion_id": suggestion_id, "enabled_command": enabled_command}


async def _handle_reject(params: dict[str, Any]) -> dict[str, Any]:
    suggestion_id = params.get("suggestion_id")
    if suggestion_id is None:
        raise ValueError("Не указан идентификатор предложения.")
    await asyncio.to_thread(service_layer.reject, PluginAgentUnitOfWork(), int(suggestion_id))
    return {"suggestion_id": suggestion_id}


async def _handle_claude_cli_status(_params: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(get_claude_auth_status)


async def _handle_claude_cli_login(_params: dict[str, Any]) -> dict[str, Any]:
    await asyncio.to_thread(start_claude_login)
    return {"message": "Открываю вход в Claude в браузере — завершите его там."}


def register_commands(dispatcher: CommandDispatcher) -> None:
    global _hot_reload_observer
    init_plugin_loader(dispatcher)
    _hot_reload_observer = start_hot_reload()
    gap_promotion_worker.start()

    dispatcher.register(
        "plugin_agent_list_suggestions",
        _handle_list_suggestions,
        dangerous=False,
        description="Показать список предложений плагинов от ИИ, ожидающих подтверждения пользователя.",
    )
    dispatcher.register(
        "plugin_agent_get_code",
        _handle_get_code,
        dangerous=False,
        description="Показать исходный код сгенерированного предложения плагина (suggestion_id).",
    )
    dispatcher.register(
        "plugin_agent_approve",
        _handle_approve,
        dangerous=False,
        description="Одобрить сгенерированное предложение плагина и включить его (suggestion_id).",
    )
    dispatcher.register(
        "plugin_agent_reject",
        _handle_reject,
        dangerous=False,
        description="Отклонить и удалить сгенерированное предложение плагина (suggestion_id).",
    )
    dispatcher.register(
        "claude_cli_status",
        _handle_claude_cli_status,
        dangerous=False,
        description="Проверить, авторизован ли Claude Code CLI на этом компьютере.",
    )
    dispatcher.register(
        "claude_cli_login",
        _handle_claude_cli_login,
        dangerous=False,
        description="Запустить процесс входа Claude Code CLI (откроется браузер).",
    )


def shutdown() -> None:
    gap_promotion_worker.stop()
    if _hot_reload_observer is not None:
        _hot_reload_observer.stop()
        _hot_reload_observer.join(timeout=5)
