from __future__ import annotations

import uuid
from pathlib import Path

from core.config import FITNESS_MEDIA_DIR

# Shared by both progress-photo uploads and meal photos (core/main.py's
# /api/fitness/progress_photos and /api/fitness/meals/photo) — both are the
# same "save one uploaded image file locally" concern, so this isn't
# fitness-progress-photo-specific despite the module name matching the
# ТЗ's file list.


def save_photo_bytes(data: bytes, suffix: str = ".jpg") -> Path:
    FITNESS_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    file_path = FITNESS_MEDIA_DIR / f"{uuid.uuid4().hex}{suffix}"
    file_path.write_bytes(data)
    return file_path


def delete_photo_file(file_path: str) -> None:
    Path(file_path).unlink(missing_ok=True)
