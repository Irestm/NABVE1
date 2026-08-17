from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace

from core import logger as logger_module


def _unique_name() -> str:
    return f"test.logger.{uuid.uuid4().hex}"


def test_get_logger_attaches_a_file_and_console_handler(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(logger_module, "settings", SimpleNamespace(log_file=tmp_path / "assistant.log"))

    log = logger_module.get_logger(_unique_name())

    assert len(log.handlers) == 2
    assert log.level == logging.INFO
    assert log.propagate is False


def test_get_logger_returns_the_same_logger_without_duplicating_handlers(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(logger_module, "settings", SimpleNamespace(log_file=tmp_path / "assistant.log"))
    name = _unique_name()

    first = logger_module.get_logger(name)
    second = logger_module.get_logger(name)

    assert first is second
    assert len(second.handlers) == 2
