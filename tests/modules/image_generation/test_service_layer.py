from __future__ import annotations

import pytest

from modules.image_generation import api_client, browser_fallback, service_layer
from modules.image_generation.uow import ImageGenerationUnitOfWork


def _uow_factory(tmp_path):
    def factory() -> ImageGenerationUnitOfWork:
        return ImageGenerationUnitOfWork(db_path=tmp_path / "state.db")

    return factory


@pytest.fixture(autouse=True)
def _isolated_images_dir(monkeypatch, tmp_path):
    images_dir = tmp_path / "generated_images"
    monkeypatch.setattr(service_layer, "GENERATED_IMAGES_DIR", images_dir)


async def test_generate_and_store_uses_the_api_when_a_key_is_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(service_layer, "ImageGenerationUnitOfWork", _uow_factory(tmp_path))
    monkeypatch.setattr(service_layer, "get_secret", lambda name: "fake-key")

    async def fake_generate_image(api_key: str, prompt: str) -> bytes:
        assert api_key == "fake-key"
        return b"api-bytes"

    monkeypatch.setattr(api_client, "generate_image", fake_generate_image)

    record = await service_layer.generate_and_store("a cat")

    assert record.source == service_layer.SOURCE_API
    assert record.image_path.read_bytes() == b"api-bytes"


async def test_generate_and_store_falls_back_to_browser_without_a_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(service_layer, "ImageGenerationUnitOfWork", _uow_factory(tmp_path))
    monkeypatch.setattr(service_layer, "get_secret", lambda name: None)

    async def fake_browser_generate(prompt: str) -> bytes:
        return b"browser-bytes"

    monkeypatch.setattr(browser_fallback, "generate_image", fake_browser_generate)

    record = await service_layer.generate_and_store("a cat")

    assert record.source == service_layer.SOURCE_BROWSER
    assert record.image_path.read_bytes() == b"browser-bytes"


async def test_generate_and_store_falls_back_to_browser_when_api_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(service_layer, "ImageGenerationUnitOfWork", _uow_factory(tmp_path))
    monkeypatch.setattr(service_layer, "get_secret", lambda name: "fake-key")

    async def fake_generate_image(api_key: str, prompt: str) -> bytes:
        raise api_client.GeminiImageGenerationError("quota exceeded")

    async def fake_browser_generate(prompt: str) -> bytes:
        return b"browser-bytes"

    monkeypatch.setattr(api_client, "generate_image", fake_generate_image)
    monkeypatch.setattr(browser_fallback, "generate_image", fake_browser_generate)

    record = await service_layer.generate_and_store("a cat")

    assert record.source == service_layer.SOURCE_BROWSER


async def test_generate_and_store_persists_the_prompt(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(service_layer, "ImageGenerationUnitOfWork", _uow_factory(tmp_path))
    monkeypatch.setattr(service_layer, "get_secret", lambda name: None)
    monkeypatch.setattr(browser_fallback, "generate_image", lambda prompt: _bytes())

    record = await service_layer.generate_and_store("a friendly robot")

    assert record.prompt == "a friendly robot"
    assert record.id is not None
    listed = service_layer.list_images()
    assert listed[0].prompt == "a friendly robot"


async def test_generate_and_store_persists_the_real_dir_path_to_the_db(monkeypatch, tmp_path) -> None:
    # Regression: dir_path is only known after the row's id is assigned, but
    # the in-memory record being updated afterward doesn't persist by
    # itself — the row must be explicitly re-saved, or a later fetch (e.g.
    # delete_image's cleanup) sees the empty placeholder dir_path the row
    # was first inserted with and silently rm -rf's nothing.
    monkeypatch.setattr(service_layer, "ImageGenerationUnitOfWork", _uow_factory(tmp_path))
    monkeypatch.setattr(service_layer, "get_secret", lambda name: None)
    monkeypatch.setattr(browser_fallback, "generate_image", lambda prompt: _bytes())

    record = await service_layer.generate_and_store("a cat")

    refetched = service_layer.get_image(record.id)
    assert refetched is not None
    assert refetched.dir_path == record.dir_path
    assert refetched.dir_path != ""


def test_get_image_returns_none_for_unknown_id(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(service_layer, "ImageGenerationUnitOfWork", _uow_factory(tmp_path))

    assert service_layer.get_image(999) is None


async def test_delete_image_removes_the_row_and_the_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(service_layer, "ImageGenerationUnitOfWork", _uow_factory(tmp_path))
    monkeypatch.setattr(service_layer, "get_secret", lambda name: None)
    monkeypatch.setattr(browser_fallback, "generate_image", lambda prompt: _bytes())

    record = await service_layer.generate_and_store("a cat")
    assert record.image_path.exists()

    deleted = service_layer.delete_image(record.id)

    assert deleted is True
    assert not record.image_path.exists()
    assert service_layer.get_image(record.id) is None


def test_delete_image_returns_false_for_unknown_id(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(service_layer, "ImageGenerationUnitOfWork", _uow_factory(tmp_path))

    assert service_layer.delete_image(999) is False


async def _bytes() -> bytes:
    return b"fallback-bytes"
