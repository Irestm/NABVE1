from __future__ import annotations

import asyncio
from typing import Any

from core.dispatcher import CommandDispatcher
from core.logger import get_logger
from modules.quizlet_clone import quizlet_auth, quizlet_scraper, service_layer
from modules.quizlet_clone.storage import QuizletUnitOfWork

logger = get_logger(__name__)


async def _handle_quizlet_login(_params: dict[str, Any]) -> dict[str, Any]:
    await quizlet_auth.login()
    return {"message": "Открываю окно входа в Quizlet — авторизуйтесь на сайте сами."}


async def _handle_quizlet_logout(_params: dict[str, Any]) -> dict[str, Any]:
    await quizlet_auth.logout()
    return {}


async def _handle_quizlet_import_session(_params: dict[str, Any]) -> dict[str, Any]:
    result = await quizlet_auth.import_session()
    message = f"Сессия импортирована из {result.source} ({result.cookies_written} cookie)."
    if result.warnings:
        message += " " + " ".join(result.warnings)
    return {"source": result.source, "cookies_written": result.cookies_written, "message": message}


async def _handle_quizlet_import_set(params: dict[str, Any]) -> dict[str, Any]:
    """Imports a Quizlet set the user doesn't have locally yet, or
    re-scrapes one already imported (ТЗ's "обновить") — both are the same
    operation (modules.quizlet_clone.service_layer.import_or_refresh_set is
    idempotent by quizlet_set_id), so a single command backs both the
    frontend's "Импортировать" and "Обновить из Quizlet" buttons."""
    quizlet_set_id = params.get("quizlet_set_id")
    if not quizlet_set_id:
        raise ValueError("Не указан идентификатор набора Quizlet.")
    title = params.get("title") or quizlet_set_id

    session = quizlet_auth.get_session()
    if not await session.is_logged_in():
        raise RuntimeError("Сначала войдите в Quizlet.")

    terms = await quizlet_scraper.scrape_set_terms(session, str(quizlet_set_id))
    study_set = service_layer.import_or_refresh_set(QuizletUnitOfWork(), str(quizlet_set_id), title, terms)
    return {
        "set_id": study_set.id,
        "title": study_set.title,
        "term_count": len(study_set.terms),
        "message": f"Набор «{study_set.title}» импортирован ({len(study_set.terms)} терминов).",
    }


async def _handle_quizlet_import_all_sets(_params: dict[str, Any]) -> dict[str, Any]:
    """Bulk version of quizlet_import_set: scrapes every set in the user's
    Quizlet library into local storage in one go, then closes the browser
    session — once everything's copied locally, Jarvis has no more use for
    the live Quizlet browser tab, and closing it frees the resources it was
    holding. One set failing to scrape doesn't abort the rest; failures are
    collected and reported instead of silently skipped."""
    session = quizlet_auth.get_session()
    if not await session.is_logged_in():
        raise RuntimeError("Сначала войдите в Quizlet.")

    library = await quizlet_scraper.list_library_sets(session)
    uow = QuizletUnitOfWork()
    imported: list[str] = []
    failed: list[str] = []
    for index, item in enumerate(library):
        if index > 0:
            # Confirmed live: scraping ~10 sets back-to-back with no pause
            # started getting blank/empty responses from Quizlet partway
            # through a library this size (no data-testid attributes at
            # all — a throttling response, not a real page) — a short,
            # human-paced gap between sets avoided it for everything after.
            await asyncio.sleep(2)
        try:
            terms = await quizlet_scraper.scrape_set_terms(session, item.quizlet_set_id)
            study_set = service_layer.import_or_refresh_set(uow, item.quizlet_set_id, item.title, terms)
            imported.append(study_set.title)
        except Exception as exc:
            logger.warning("Failed to import Quizlet set %s (%s): %s", item.quizlet_set_id, item.title, exc)
            failed.append(item.title)

    # Just closes the browser tab/process — unlike quizlet_auth.logout(),
    # the saved session/profile is kept, so is_logged_in() still reports
    # true and a later manual refresh can reopen it without a fresh login.
    await session.close()

    message = f"Импортировано наборов: {len(imported)} из {len(library)}. Сессия браузера закрыта."
    if failed:
        message += f" Не удалось: {', '.join(failed)}."
    return {"imported_count": len(imported), "total_count": len(library), "failed": failed, "message": message}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "quizlet_login",
        _handle_quizlet_login,
        dangerous=False,
        description="Открыть видимое окно браузера на странице входа Quizlet, чтобы пользователь вошёл сам.",
    )
    dispatcher.register(
        "quizlet_logout",
        _handle_quizlet_logout,
        dangerous=False,
        description="Сбросить сессию браузера Quizlet до гостевой (стирает папку с постоянным профилем).",
    )
    dispatcher.register(
        "quizlet_import_session",
        _handle_quizlet_import_session,
        dangerous=False,
        description=(
            "Скопировать уже вошедшую сессию Quizlet из настоящего браузера пользователя "
            "(Firefox/Chrome) вместо попытки нового автоматического входа."
        ),
    )
    dispatcher.register(
        "quizlet_import_set",
        _handle_quizlet_import_set,
        dangerous=False,
        description="Спарсить и импортировать (или обновить) один набор Quizlet по id (quizlet_set_id, опционально title).",
    )
    dispatcher.register(
        "quizlet_import_all_sets",
        _handle_quizlet_import_all_sets,
        dangerous=False,
        description=(
            "Спарсить и импортировать все наборы из библиотеки Quizlet в локальное хранилище за один "
            "раз, затем закрыть сессию браузера — после этого всё нужное уже скопировано локально."
        ),
    )
