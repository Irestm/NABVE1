from __future__ import annotations

import pytest

from core.dispatcher import CommandDispatcher
from modules.messaging import service_layer as messaging_service_layer
from modules.messaging.domain import PendingMessage
from modules.text_editing import dispatcher as text_dispatcher
from modules.text_editing import service_layer


def test_register_commands_registers_both_commands() -> None:
    dispatcher = CommandDispatcher()

    text_dispatcher.register_commands(dispatcher)

    names = {c.name for c in dispatcher.list_commands()}
    assert names == {text_dispatcher.COMMAND_EDIT_TEXT, text_dispatcher.COMMAND_EDIT_PENDING_MESSAGE}


async def test_edit_text_handler_delegates_to_service_layer(monkeypatch) -> None:
    async def fake_edit_text(text: str, instruction: str) -> str:
        assert text == "исходный"
        assert instruction == "сократи"
        return "короткий"

    monkeypatch.setattr(service_layer, "edit_text", fake_edit_text)

    result = await text_dispatcher._edit_text({"text": "исходный", "instruction": "сократи"})

    assert result == {"message": "короткий", "edited_text": "короткий"}


async def test_edit_text_handler_rejects_missing_text() -> None:
    with pytest.raises(ValueError):
        await text_dispatcher._edit_text({"instruction": "сократи"})


async def test_edit_text_handler_rejects_missing_instruction() -> None:
    with pytest.raises(ValueError):
        await text_dispatcher._edit_text({"text": "текст"})


async def test_edit_pending_message_handler_edits_the_found_message(monkeypatch) -> None:
    pending = PendingMessage(
        id=7, source="telegram", sender_identifier="@ira", sender_label="Ира", text="привет, как дела"
    )
    monkeypatch.setattr(messaging_service_layer, "get_message", lambda uow, message_id: pending)

    async def fake_edit_text(text: str, instruction: str) -> str:
        assert text == "привет, как дела"
        assert instruction == "сделай формальнее"
        return "Здравствуйте, как ваши дела?"

    monkeypatch.setattr(service_layer, "edit_text", fake_edit_text)

    result = await text_dispatcher._edit_pending_message(
        {"message_id": "7", "instruction": "сделай формальнее"}
    )

    assert result["edited_text"] == "Здравствуйте, как ваши дела?"
    assert result["message_id"] == 7
    assert "Здравствуйте" in result["message"]


async def test_edit_pending_message_handler_raises_when_message_not_found(monkeypatch) -> None:
    monkeypatch.setattr(messaging_service_layer, "get_message", lambda uow, message_id: None)

    with pytest.raises(ValueError):
        await text_dispatcher._edit_pending_message({"message_id": "999", "instruction": "сократи"})


async def test_edit_pending_message_handler_rejects_missing_message_id() -> None:
    with pytest.raises(ValueError):
        await text_dispatcher._edit_pending_message({"instruction": "сократи"})


async def test_edit_pending_message_handler_rejects_missing_instruction() -> None:
    with pytest.raises(ValueError):
        await text_dispatcher._edit_pending_message({"message_id": "7"})
