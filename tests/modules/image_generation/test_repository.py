from __future__ import annotations

from modules.image_generation.domain import GeneratedImage
from modules.image_generation.uow import ImageGenerationUnitOfWork


def test_add_then_get_round_trips(tmp_path) -> None:
    with ImageGenerationUnitOfWork(db_path=tmp_path / "state.db") as uow:
        record = GeneratedImage(dir_path="/tmp/x", prompt="a cat", source="api")
        image_id = uow.images.add(record)
        uow.commit()

    with ImageGenerationUnitOfWork(db_path=tmp_path / "state.db") as uow:
        fetched = uow.images.get(image_id)

    assert fetched is not None
    assert fetched.prompt == "a cat"
    assert fetched.source == "api"
    assert fetched.dir_path == "/tmp/x"
    assert fetched.created_at is not None


def test_get_returns_none_for_unknown_id(tmp_path) -> None:
    with ImageGenerationUnitOfWork(db_path=tmp_path / "state.db") as uow:
        assert uow.images.get(999) is None


def test_list_all_orders_newest_first(tmp_path) -> None:
    with ImageGenerationUnitOfWork(db_path=tmp_path / "state.db") as uow:
        uow.images.add(GeneratedImage(dir_path="/tmp/1", prompt="first", source="api"))
        uow.images.add(GeneratedImage(dir_path="/tmp/2", prompt="second", source="api"))
        uow.commit()

    with ImageGenerationUnitOfWork(db_path=tmp_path / "state.db") as uow:
        images = uow.images.list_all()

    assert [i.prompt for i in images] == ["second", "first"]


def test_delete_removes_the_row(tmp_path) -> None:
    with ImageGenerationUnitOfWork(db_path=tmp_path / "state.db") as uow:
        image_id = uow.images.add(GeneratedImage(dir_path="/tmp/1", prompt="first", source="api"))
        uow.commit()

    with ImageGenerationUnitOfWork(db_path=tmp_path / "state.db") as uow:
        deleted = uow.images.delete(image_id)
        uow.commit()

    assert deleted is True
    with ImageGenerationUnitOfWork(db_path=tmp_path / "state.db") as uow:
        assert uow.images.get(image_id) is None


def test_delete_returns_false_for_unknown_id(tmp_path) -> None:
    with ImageGenerationUnitOfWork(db_path=tmp_path / "state.db") as uow:
        assert uow.images.delete(999) is False
