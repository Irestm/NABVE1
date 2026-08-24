from __future__ import annotations

from typing import Any

from core.dispatcher import CommandDispatcher
from modules.messaging import service_layer as messaging_service_layer
from modules.messaging.uow import MessagingUnitOfWork
from modules.text_editing import service_layer

COMMAND_EDIT_TEXT = "edit_text"
COMMAND_EDIT_PENDING_MESSAGE = "edit_pending_message"


async def _edit_text(params: dict[str, Any]) -> dict[str, Any]:
    text = params.get("text")
    instruction = params.get("instruction")
    if not text:
        raise ValueError("Не указан текст для редактирования.")
    if not instruction:
        raise ValueError("Не указана инструкция.")
    edited = await service_layer.edit_text(text, instruction)
    return {"message": edited, "edited_text": edited}


async def _edit_pending_message(params: dict[str, Any]) -> dict[str, Any]:
    message_id = params.get("message_id")
    instruction = params.get("instruction")
    if message_id is None:
        raise ValueError("Не указан идентификатор сообщения.")
    if not instruction:
        raise ValueError("Не указана инструкция.")
    pending = messaging_service_layer.get_message(MessagingUnitOfWork(), int(message_id))
    if pending is None:
        raise ValueError(f"Нет ожидающего сообщения с id {message_id}.")
    edited = await service_layer.edit_text(pending.text, instruction)
    return {"message": f"Вот что получилось: {edited}", "edited_text": edited, "message_id": pending.id}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        COMMAND_EDIT_TEXT, _edit_text, description="Отредактировать вставленный текст по инструкции"
    )
    dispatcher.register(
        COMMAND_EDIT_PENDING_MESSAGE,
        _edit_pending_message,
        description="Отредактировать текст ожидающего сообщения",
    )
