from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

IMAGE_FILENAME = "image.png"


@dataclass
class GeneratedImage:
    dir_path: str
    prompt: str
    source: str
    id: int | None = None
    created_at: datetime | None = None

    @property
    def image_path(self) -> Path:
        return Path(self.dir_path) / IMAGE_FILENAME
