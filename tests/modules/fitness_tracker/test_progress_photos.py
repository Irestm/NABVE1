from __future__ import annotations

import pytest

from modules.fitness_tracker import progress_photos


@pytest.fixture(autouse=True)
def _isolated_media_dir(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(progress_photos, "FITNESS_MEDIA_DIR", tmp_path)


def test_save_photo_bytes_writes_the_file_under_the_media_dir(tmp_path) -> None:
    path = progress_photos.save_photo_bytes(b"fake-jpeg", suffix=".jpg")

    assert path.parent == tmp_path
    assert path.suffix == ".jpg"
    assert path.read_bytes() == b"fake-jpeg"


def test_delete_photo_file_removes_an_existing_file(tmp_path) -> None:
    path = progress_photos.save_photo_bytes(b"fake-jpeg")

    progress_photos.delete_photo_file(str(path))

    assert not path.exists()


def test_delete_photo_file_is_a_no_op_for_a_missing_file(tmp_path) -> None:
    progress_photos.delete_photo_file(str(tmp_path / "does-not-exist.jpg"))
