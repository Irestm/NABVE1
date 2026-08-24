from __future__ import annotations

import pytest

from modules.os_agent import session


@pytest.fixture(autouse=True)
def _reset_session() -> None:
    session._active = False
    yield
    session._active = False


def test_inactive_by_default() -> None:
    assert session.is_active() is False


def test_start_activates() -> None:
    session.start()
    assert session.is_active() is True


def test_finish_deactivates() -> None:
    session.start()
    session.finish()
    assert session.is_active() is False


def test_finish_without_start_is_a_no_op() -> None:
    session.finish()
    assert session.is_active() is False
