from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.models import CommandDescriptor
from modules.ai_bridge import intent_classifier


def _commands() -> list[CommandDescriptor]:
    return [
        CommandDescriptor(name="set_volume", dangerous=False, description="Set system volume (percent)"),
        CommandDescriptor(name="open_app", dangerous=False, description="Open an application"),
    ]


@pytest.mark.asyncio
async def test_classify_accepts_a_near_verbatim_command_name_without_calling_the_provider() -> None:
    manager = AsyncMock()

    result = await intent_classifier.classify("set volume", _commands(), manager)

    assert result.matched_command == "set_volume"
    assert result.is_direct_question is False
    manager.send_prompt.assert_not_called()


@pytest.mark.asyncio
async def test_classify_asks_the_provider_when_no_direct_match() -> None:
    manager = AsyncMock()
    manager.send_prompt.return_value = (
        '{"matched_command": "open_app", "params": {"target": "spotify"}, "is_direct_question": false}'
    )

    result = await intent_classifier.classify("запусти спотифай", _commands(), manager)

    assert result.matched_command == "open_app"
    assert result.params == {"target": "spotify"}
    assert result.is_direct_question is False


@pytest.mark.asyncio
async def test_classify_treats_unparseable_json_as_a_question() -> None:
    manager = AsyncMock()
    manager.send_prompt.return_value = "not json at all"

    result = await intent_classifier.classify("какая погода в москве", _commands(), manager)

    assert result.matched_command is None
    assert result.is_direct_question is True


@pytest.mark.asyncio
async def test_classify_rejects_a_command_name_the_model_invented() -> None:
    manager = AsyncMock()
    manager.send_prompt.return_value = (
        '{"matched_command": "delete_everything", "params": {}, "is_direct_question": false}'
    )

    result = await intent_classifier.classify("привет", _commands(), manager)

    assert result.matched_command is None


@pytest.mark.asyncio
async def test_classify_falls_back_to_a_question_when_the_provider_raises() -> None:
    manager = AsyncMock()
    manager.send_prompt.side_effect = RuntimeError("no provider logged in")

    result = await intent_classifier.classify("привет", _commands(), manager)

    assert result.matched_command is None
    assert result.is_direct_question is True
