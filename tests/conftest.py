from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture
def tmp_db_path() -> Iterator[Path]:
    path = Path(tempfile.mktemp(suffix=".db"))
    yield path
    path.unlink(missing_ok=True)
