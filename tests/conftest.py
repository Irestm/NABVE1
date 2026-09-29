from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

os.environ.setdefault("ASSISTANT_GPU_WORKER_DISABLED", "1")


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


@pytest.fixture(autouse=True)
def _isolate_providers_config(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from modules.ai_bridge.providers import config as providers_config

    monkeypatch.setattr(
        providers_config, "USER_CONFIG_PATH", tmp_path_factory.mktemp("providers") / "providers.yaml"
    )


@pytest.fixture(autouse=True)
def _isolate_english_learning_storage(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from modules.english_learning import listening, subtitle_store, uow

    root = tmp_path_factory.mktemp("english_learning")
    monkeypatch.setattr(uow, "ENGLISH_DB_PATH", root / "english_learning.db")
    monkeypatch.setattr(subtitle_store, "SUBTITLES_DIR", root / "subtitles")
    monkeypatch.setattr(listening, "CLIPS_DIR", root / "listening")
