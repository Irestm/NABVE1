from __future__ import annotations

from core.dispatcher import CommandDispatcher
from modules.image_generation import dispatcher as image_dispatcher
from modules.image_generation import service_layer
from modules.image_generation.domain import GeneratedImage


def test_register_commands_registers_the_command() -> None:
    dispatcher = CommandDispatcher()

    image_dispatcher.register_commands(dispatcher)

    names = {c.name for c in dispatcher.list_commands()}
    assert names == {image_dispatcher.COMMAND_GENERATE_IMAGE}


async def test_generate_image_handler_delegates_and_returns_the_image_id(monkeypatch) -> None:
    async def fake_generate_and_store(prompt: str) -> GeneratedImage:
        assert prompt == "a cat"
        return GeneratedImage(dir_path="/tmp/1", prompt=prompt, source="api", id=42)

    monkeypatch.setattr(service_layer, "generate_and_store", fake_generate_and_store)

    result = await image_dispatcher._generate_image({"prompt": "a cat"})

    assert result["image_id"] == 42
    assert "message" in result
