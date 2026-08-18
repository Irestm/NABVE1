from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.dispatcher import CommandDispatcher
from modules.quizlet_clone import handlers
from modules.quizlet_clone.models import LibrarySetSummary, SetSource, StudySet


def test_register_commands_registers_the_three_quizlet_commands() -> None:
    dispatcher = CommandDispatcher()

    handlers.register_commands(dispatcher)

    names = {c.name for c in dispatcher.list_commands()}
    assert {
        "quizlet_login",
        "quizlet_logout",
        "quizlet_import_session",
        "quizlet_import_set",
        "quizlet_import_all_sets",
    } <= names


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
    with pytest.raises(ValueError, match="идентификатор набора"):
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


@pytest.mark.asyncio
async def test_handle_quizlet_import_all_sets_requires_login(monkeypatch) -> None:
    fake_session = MagicMock(is_logged_in=AsyncMock(return_value=False))
    monkeypatch.setattr(handlers.quizlet_auth, "get_session", lambda: fake_session)

    with pytest.raises(RuntimeError, match="Сначала войдите в Quizlet"):
        await handlers._handle_quizlet_import_all_sets({})


@pytest.mark.asyncio
async def test_handle_quizlet_import_all_sets_imports_everything_then_closes_the_browser(monkeypatch) -> None:
    monkeypatch.setattr(handlers.asyncio, "sleep", AsyncMock())
    fake_session = MagicMock(is_logged_in=AsyncMock(return_value=True), close=AsyncMock())
    monkeypatch.setattr(handlers.quizlet_auth, "get_session", lambda: fake_session)

    library = [
        LibrarySetSummary(quizlet_set_id="1", title="Испанский", term_count=2),
        LibrarySetSummary(quizlet_set_id="2", title="Немецкий", term_count=3),
    ]
    monkeypatch.setattr(handlers.quizlet_scraper, "list_library_sets", AsyncMock(return_value=library))
    monkeypatch.setattr(handlers.quizlet_scraper, "scrape_set_terms", AsyncMock(return_value=[("a", "b")]))

    def fake_import(_uow, quizlet_set_id, title, _terms):
        study_set = StudySet(id=f"s{quizlet_set_id}", title=title, source=SetSource.QUIZLET_IMPORT, quizlet_set_id=quizlet_set_id)
        study_set.terms = []
        return study_set

    monkeypatch.setattr(handlers.service_layer, "import_or_refresh_set", fake_import)

    result = await handlers._handle_quizlet_import_all_sets({})

    assert result["imported_count"] == 2
    assert result["total_count"] == 2
    assert result["failed"] == []
    fake_session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_quizlet_import_all_sets_reports_failures_without_aborting(monkeypatch) -> None:
    monkeypatch.setattr(handlers.asyncio, "sleep", AsyncMock())
    fake_session = MagicMock(is_logged_in=AsyncMock(return_value=True), close=AsyncMock())
    monkeypatch.setattr(handlers.quizlet_auth, "get_session", lambda: fake_session)

    library = [
        LibrarySetSummary(quizlet_set_id="1", title="Ok", term_count=1),
        LibrarySetSummary(quizlet_set_id="2", title="Broken", term_count=1),
    ]
    monkeypatch.setattr(handlers.quizlet_scraper, "list_library_sets", AsyncMock(return_value=library))

    async def fake_scrape(_session, quizlet_set_id):
        if quizlet_set_id == "2":
            raise RuntimeError("layout changed")
        return [("a", "b")]

    monkeypatch.setattr(handlers.quizlet_scraper, "scrape_set_terms", fake_scrape)

    def fake_import(_uow, quizlet_set_id, title, _terms):
        study_set = StudySet(id=f"s{quizlet_set_id}", title=title, source=SetSource.QUIZLET_IMPORT, quizlet_set_id=quizlet_set_id)
        study_set.terms = []
        return study_set

    monkeypatch.setattr(handlers.service_layer, "import_or_refresh_set", fake_import)

    result = await handlers._handle_quizlet_import_all_sets({})

    assert result["imported_count"] == 1
    assert result["total_count"] == 2
    assert result["failed"] == ["Broken"]
    fake_session.close.assert_awaited_once()
