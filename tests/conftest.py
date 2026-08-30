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


@pytest.fixture(autouse=True)
def _isolate_conversation_log(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # modules/conversation_log's process-wide singleton otherwise appends
    # to the real data/conversation_log.jsonl - any pipeline/web_pipeline/
    # API test that reaches a spoken or typed reply would pollute it.
    from modules.conversation_log import conversation_log

    log_path = tmp_path_factory.mktemp("conversation_log") / "conversation_log.jsonl"
    monkeypatch.setattr(conversation_log, "_path", log_path)
