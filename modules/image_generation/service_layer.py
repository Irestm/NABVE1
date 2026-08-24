from __future__ import annotations

import shutil
from pathlib import Path

from core.config import GENERATED_IMAGES_DIR
from core.logger import get_logger
from core.secret_store import get_secret
from modules.ai_bridge.api_providers import GEMINI_API_KEY_SECRET_NAME
from modules.image_generation import api_client, browser_fallback
from modules.image_generation.domain import GeneratedImage
from modules.image_generation.uow import ImageGenerationUnitOfWork

logger = get_logger(__name__)

SOURCE_API = "api"
SOURCE_BROWSER = "browser"


async def _generate_bytes(prompt: str) -> tuple[bytes, str]:
    api_key = get_secret(GEMINI_API_KEY_SECRET_NAME)
    if api_key:
        try:
            return await api_client.generate_image(api_key, prompt), SOURCE_API
        except api_client.GeminiImageGenerationError:
            logger.exception("Gemini API image generation failed for %r, falling back to browser", prompt)
    return await browser_fallback.generate_image(prompt), SOURCE_BROWSER


async def generate_and_store(prompt: str) -> GeneratedImage:
    image_bytes, source = await _generate_bytes(prompt)

    with ImageGenerationUnitOfWork() as uow:
        record = GeneratedImage(dir_path="", prompt=prompt, source=source)
        image_id = uow.images.add(record)
        record.id = image_id
        record.dir_path = str(GENERATED_IMAGES_DIR / str(image_id))
        Path(record.dir_path).mkdir(parents=True, exist_ok=True)
        record.image_path.write_bytes(image_bytes)
        uow.images.update(record)
        uow.commit()
        return record


def list_images() -> list[GeneratedImage]:
    with ImageGenerationUnitOfWork() as uow:
        return uow.images.list_all()


def get_image(image_id: int) -> GeneratedImage | None:
    with ImageGenerationUnitOfWork() as uow:
        return uow.images.get(image_id)


def delete_image(image_id: int) -> bool:
    with ImageGenerationUnitOfWork() as uow:
        record = uow.images.get(image_id)
        if record is None:
            return False
        deleted = uow.images.delete(image_id)
        uow.commit()
    if deleted:
        shutil.rmtree(record.dir_path, ignore_errors=True)
    return deleted
