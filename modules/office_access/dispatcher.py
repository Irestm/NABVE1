"""Entry point for Jarvis <-> LibreOffice Base voice control.

process_access_command(text) is the module's whole public surface for
actually running a command: ensure the shared office bridge process is up ->
parse -> send -> speak the result. register_commands(dispatcher) wires
exactly one command ("access_command", a raw-text param) into the shared
dispatcher — same reasoning as modules/office_writer/dispatcher.py's
register_commands docstring.
"""

from __future__ import annotations

from typing import Any

from core.dispatcher import CommandDispatcher
from core.logger import get_logger
from modules.office_access import command_parser
from modules.office_access.bridge_client import OfficeAccessUnavailableError, office_access_bridge_client

logger = get_logger(__name__)

_UNAVAILABLE_MESSAGE = "Не удалось подключиться к LibreOffice Base, попробуй ещё раз через пару секунд."


def _format_rows(data: dict[str, Any]) -> str:
    rows = data.get("rows") or []
    if not rows:
        return "Записей не найдено."
    columns = data.get("columns") or []
    lines = []
    for index, row in enumerate(rows, start=1):
        pairs = ", ".join(f"{column}: {row.get(column, '')}" for column in columns)
        lines.append(f"{index}. {pairs}")
    return f"Нашёл {len(rows)} записей. " + " ".join(lines)


def _success_message(action: str, params: dict[str, Any], data: dict[str, Any]) -> str:
    if action == "open_database":
        return f"Открыта база {data.get('opened', '')}".strip()
    if action == "save_database":
        return "База данных сохранена"
    if action == "close_database":
        return "База данных закрыта"
    if action == "create_table":
        return f"Таблица {params.get('name', '')} создана".strip()
    if action == "delete_table":
        return f"Таблица {params.get('name', '')} удалена".strip()
    if action == "list_tables":
        tables = data.get("tables") or []
        return f"Таблицы: {', '.join(tables)}" if tables else "В базе нет таблиц."
    if action == "insert_row":
        return "Запись добавлена"
    if action == "update_rows":
        return "Записи обновлены"
    if action == "delete_rows":
        return "Записи удалены"
    if action == "list_rows":
        return _format_rows(data)
    return "Готово."


async def process_access_command(text: str) -> str:
    """1. parse `text` (rule-based, then AI structuring as a fallback);
    2. make sure the shared office bridge process is up, launching it if
    needed; 3. send the command; 4. return a short Russian sentence for TTS
    describing what happened. Never raises."""
    parsed = await command_parser.parse_command(text)
    if parsed is None:
        return "Не понял, что нужно сделать с базой данных."

    try:
        await office_access_bridge_client.ensure_bridge_running()
        response = await office_access_bridge_client.send_command(parsed.action, parsed.params)
    except OfficeAccessUnavailableError as exc:
        logger.warning("Office Access command '%s' failed: %s", parsed.action, exc)
        return _UNAVAILABLE_MESSAGE

    if response.get("status") != "success":
        message = response.get("message") or "неизвестная ошибка"
        logger.info("Office Access rejected command '%s': %s", parsed.action, message)
        return message

    data = response.get("data") or {}
    return _success_message(parsed.action, parsed.params, data)


async def _handle_access_command(params: dict[str, Any]) -> dict[str, Any]:
    text = params.get("text")
    if not text:
        raise ValueError("Missing required parameter 'text'")
    message = await process_access_command(text)
    return {"message": message}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "access_command",
        _handle_access_command,
        dangerous=False,
        description=(
            "Управление базой данных LibreOffice Base голосом (аналог Access — свой формат .odb с "
            "встроенной HSQLDB, файлы Microsoft Access .accdb/.mdb не поддерживаются): открытие/"
            "сохранение/закрытие базы, создание и удаление таблиц, добавление/изменение/удаление записей, "
            "просмотр записей и списка таблиц. Использовать при любом упоминании Access, базы данных, "
            "таблиц с записями (не путать с таблицами Word/Excel) (text — полная исходная фраза "
            "пользователя)."
        ),
    )
