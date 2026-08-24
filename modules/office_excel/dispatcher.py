"""Entry point for Jarvis <-> LibreOffice Calc voice control.

process_excel_command(text) is the module's whole public surface for
actually running a command: ensure the shared office bridge process is up ->
parse -> send -> speak the result. register_commands(dispatcher) wires
exactly one command ("excel_command", a raw-text param) into the shared
dispatcher — same reasoning as modules/office_writer/dispatcher.py's
register_commands docstring.
"""

from __future__ import annotations

from typing import Any

from core.dispatcher import CommandDispatcher
from core.logger import get_logger
from modules.office_excel import command_parser
from modules.office_excel.bridge_client import OfficeExcelUnavailableError, office_excel_bridge_client

logger = get_logger(__name__)

_UNAVAILABLE_MESSAGE = "Не удалось подключиться к LibreOffice Calc, попробуй ещё раз через пару секунд."


def _success_message(action: str, params: dict[str, Any], data: dict[str, Any]) -> str:
    if action == "open_spreadsheet":
        return f"Открыт {data.get('opened', 'файл')}"
    if action == "save_spreadsheet":
        return "Таблица сохранена"
    if action == "close_spreadsheet":
        return "Таблица закрыта"
    if action == "calc_undo":
        return "Действие отменено"
    if action == "calc_redo":
        return "Действие повторено"
    if action == "set_cell_value":
        return "Готово"
    if action == "clear_range":
        return "Очищено"
    if action == "set_formula":
        return "Формула вставлена"
    if action == "set_cell_format":
        return "Форматирование применено"
    if action in ("sheet_insert_row", "sheet_insert_column"):
        return "Добавлено"
    if action in ("sheet_delete_row", "sheet_delete_column"):
        return "Удалено"
    if action == "sheet_add":
        return f"Добавлен лист {data.get('name', '')}".strip()
    if action == "sheet_rename":
        return "Лист переименован"
    if action == "sheet_switch":
        return "Переключено на другой лист"
    return "Готово."


async def process_excel_command(text: str) -> str:
    """1. parse `text` (rule-based, then AI structuring as a fallback);
    2. make sure the shared office bridge process is up, launching it if
    needed; 3. send the command (its own "open_spreadsheet" handler
    launches soffice itself if it isn't running yet); 4. return a short
    Russian sentence for TTS describing what happened. Never raises."""
    parsed = await command_parser.parse_command(text)
    if parsed is None:
        return "Не понял, что нужно сделать в Calc."

    try:
        await office_excel_bridge_client.ensure_bridge_running()
        response = await office_excel_bridge_client.send_command(parsed.action, parsed.params)
    except OfficeExcelUnavailableError as exc:
        logger.warning("Office Excel command '%s' failed: %s", parsed.action, exc)
        return _UNAVAILABLE_MESSAGE

    if response.get("status") != "success":
        message = response.get("message") or "неизвестная ошибка"
        logger.info("Office Excel rejected command '%s': %s", parsed.action, message)
        return message

    data = response.get("data") or {}
    return _success_message(parsed.action, parsed.params, data)


async def _handle_excel_command(params: dict[str, Any]) -> dict[str, Any]:
    text = params.get("text")
    if not text:
        raise ValueError("Missing required parameter 'text'")
    message = await process_excel_command(text)
    return {"message": message}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "excel_command",
        _handle_excel_command,
        dangerous=False,
        description=(
            "Управление табличным редактором LibreOffice Calc голосом: открытие/сохранение/закрытие "
            "таблицы, ввод значений и формул в ячейки, очистка ячеек/диапазонов, форматирование ячеек "
            "(жирный, курсив, подчёркивание, размер и цвет шрифта, заливка, выравнивание), вставка и "
            "удаление строк и столбцов, добавление/переименование/переключение листов, отмена и повтор "
            "действия. Использовать при любом упоминании Excel, Calc, LibreOffice или работы с таблицей/"
            "ячейками (text — полная исходная фраза пользователя)."
        ),
    )
