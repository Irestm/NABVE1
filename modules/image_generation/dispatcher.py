from __future__ import annotations

from typing import Any

from core.dispatcher import CommandDispatcher
from modules.image_generation import service_layer

COMMAND_GENERATE_IMAGE = "generate_image"


async def _generate_image(params: dict[str, Any]) -> dict[str, Any]:
    image = await service_layer.generate_and_store(params["prompt"])
    return {"message": "Изображение готово, показываю.", "image_id": image.id}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(COMMAND_GENERATE_IMAGE, _generate_image, description="Сгенерировать изображение по описанию")
