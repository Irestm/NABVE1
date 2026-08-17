from __future__ import annotations

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


async def _handle_quizlet_import_set(params: dict[str, Any]) -> dict[str, Any]:
    """Imports a Quizlet set the user doesn't have locally yet, or
    re-scrapes one already imported (ТЗ's "обновить") — both are the same
    operation (modules.quizlet_clone.service_layer.import_or_refresh_set is
    idempotent by quizlet_set_id), so a single command backs both the
    frontend's "Импортировать" and "Обновить из Quizlet" buttons."""
    quizlet_set_id = params.get("quizlet_set_id")
    if not quizlet_set_id:
        raise ValueError("Missing required parameter 'quizlet_set_id'")
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


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "quizlet_login",
        _handle_quizlet_login,
        dangerous=False,
        description="Open a visible browser window on Quizlet's own login page so the user can log in themselves.",
    )
    dispatcher.register(
        "quizlet_logout",
        _handle_quizlet_logout,
        dangerous=False,
        description="Reset the Quizlet browser session back to guest (wipes the persistent profile directory).",
    )
    dispatcher.register(
        "quizlet_import_set",
        _handle_quizlet_import_set,
        dangerous=False,
        description="Scrape and import (or re-scrape/refresh) one Quizlet set by id (quizlet_set_id, optional title).",
    )
