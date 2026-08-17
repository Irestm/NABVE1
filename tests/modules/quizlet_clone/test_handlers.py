from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.dispatcher import CommandDispatcher
from modules.quizlet_clone import handlers
from modules.quizlet_clone.models import SetSource, StudySet


def test_register_commands_registers_the_three_quizlet_commands() -> None:
    dispatcher = CommandDispatcher()

    handlers.register_commands(dispatcher)

    names = {c.name for c in dispatcher.list_commands()}
    assert {"quizlet_login", "quizlet_logout", "quizlet_import_set"} <= names


@pytest.mark.asyncio
async def test_handle_quizlet_login_calls_auth_login(monkeypatch) -> None:
    login_mock = AsyncMock()
    monkeypatch.setattr(handlers.quizlet_auth, "login", login_mock)

    result = await handlers._handle_quizlet_login({})

    login_mock.assert_awaited_once()
    assert "message" in result


@pytest.mark.asyncio
async def test_handle_quizlet_logout_calls_auth_logout(monkeypatch) -> None:
    logout_mock = AsyncMock()
    monkeypatch.setattr(handlers.quizlet_auth, "logout", logout_mock)

    await handlers._handle_quizlet_logout({})

    logout_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_quizlet_import_set_requires_quizlet_set_id() -> None:
    with pytest.raises(ValueError, match="quizlet_set_id"):
        await handlers._handle_quizlet_import_set({})


@pytest.mark.asyncio
async def test_handle_quizlet_import_set_requires_login(monkeypatch) -> None:
    fake_session = MagicMock(is_logged_in=AsyncMock(return_value=False))
    monkeypatch.setattr(handlers.quizlet_auth, "get_session", lambda: fake_session)

    with pytest.raises(RuntimeError, match="Сначала войдите в Quizlet"):
        await handlers._handle_quizlet_import_set({"quizlet_set_id": "123456"})


@pytest.mark.asyncio
async def test_handle_quizlet_import_set_scrapes_and_imports_when_logged_in(monkeypatch) -> None:
    fake_session = MagicMock(is_logged_in=AsyncMock(return_value=True))
    monkeypatch.setattr(handlers.quizlet_auth, "get_session", lambda: fake_session)

    scrape_mock = AsyncMock(return_value=[("hola", "привет")])
    monkeypatch.setattr(handlers.quizlet_scraper, "scrape_set_terms", scrape_mock)

    imported_set = StudySet(id="s1", title="Испанский", source=SetSource.QUIZLET_IMPORT, quizlet_set_id="123456")
    imported_set.terms = []
    import_mock = MagicMock(return_value=imported_set)
    monkeypatch.setattr(handlers.service_layer, "import_or_refresh_set", import_mock)

    result = await handlers._handle_quizlet_import_set({"quizlet_set_id": "123456", "title": "Испанский"})

    scrape_mock.assert_awaited_once_with(fake_session, "123456")
    import_mock.assert_called_once()
    assert result["set_id"] == "s1"
    assert result["title"] == "Испанский"
