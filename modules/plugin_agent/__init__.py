from __future__ import annotations

import asyncio

from core.logger import get_logger
from core.message_bus import message_bus
from modules.plugin_agent.events import UnhandledQuestionAsked
from modules.plugin_agent.handlers import register_commands, shutdown
from modules.plugin_agent.plugin_loader import match_command
from modules.plugin_agent.service_layer import record_question
from modules.plugin_agent.uow import PluginAgentUnitOfWork

logger = get_logger(__name__)


async def _handle_unhandled_question(event: UnhandledQuestionAsked) -> None:
    # A plugin that already covers this text isn't a "gap" — checked here
    # (not inside service_layer.record_question) because it's a query
    # against the plugin registry, a different concern from candidate
    # lifecycle bookkeeping.
    if match_command(event.text) is not None:
        return
    await asyncio.to_thread(record_question, PluginAgentUnitOfWork(), event.text)


message_bus.subscribe(UnhandledQuestionAsked, _handle_unhandled_question)

__all__ = ["register_commands", "shutdown"]
