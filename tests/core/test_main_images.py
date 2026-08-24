from __future__ import annotations

from fastapi.testclient import TestClient

import core.main as main_module
from core.config import settings
from core.main import app
from modules.image_generation import service_layer
from modules.image_generation.uow import ImageGenerationUnitOfWork

client = TestClient(app)
AUTH = {"X-Assistant-Token": settings.api_token}


def _uow_factory(tmp_path):
    def factory() -> ImageGenerationUnitOfWork:
        return ImageGenerationUnitOfWork(db_path=tmp_path / "state.db")

    return factory


def _isolate(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(service_layer, "ImageGenerationUnitOfWork", _uow_factory(tmp_path))
    monkeypatch.setattr(service_layer, "GENERATED_IMAGES_DIR", tmp_path / "generated_images")


def test_list_images_empty_by_default(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)

    response = client.get("/api/images", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == []


def test_list_images_without_auth_is_rejected() -> None:
    response = client.get("/api/images")

    assert response.status_code == 401


async def test_list_images_returns_a_stored_image(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(service_layer, "get_secret", lambda name: None)

    from modules.image_generation import browser_fallback

    async def fake_generate(prompt: str) -> bytes:
        return b"fake-png"

    monkeypatch.setattr(browser_fallback, "generate_image", fake_generate)
    record = await service_layer.generate_and_store("a cat")

    response = client.get("/api/images", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == record.id
    assert body[0]["prompt"] == "a cat"


async def test_get_image_file_returns_the_bytes(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(service_layer, "get_secret", lambda name: None)

    from modules.image_generation import browser_fallback

    async def fake_generate(prompt: str) -> bytes:
        return b"fake-png-bytes"

    monkeypatch.setattr(browser_fallback, "generate_image", fake_generate)
    record = await service_layer.generate_and_store("a cat")

    response = client.get(f"/api/images/{record.id}/file", headers=AUTH)

    assert response.status_code == 200
    assert response.content == b"fake-png-bytes"


def test_get_image_file_404s_for_unknown_id(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)

    response = client.get("/api/images/999/file", headers=AUTH)

    assert response.status_code == 404


async def test_delete_image_removes_it(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(service_layer, "get_secret", lambda name: None)

    from modules.image_generation import browser_fallback

    async def fake_generate(prompt: str) -> bytes:
        return b"fake-png"

    monkeypatch.setattr(browser_fallback, "generate_image", fake_generate)
    record = await service_layer.generate_and_store("a cat")

    response = client.delete(f"/api/images/{record.id}", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"deleted": True}
    assert client.get("/api/images", headers=AUTH).json() == []


def test_delete_image_404s_for_unknown_id(monkeypatch, tmp_path) -> None:
    _isolate(monkeypatch, tmp_path)

    response = client.delete("/api/images/999", headers=AUTH)

    assert response.status_code == 404
