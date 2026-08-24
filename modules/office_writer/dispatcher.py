"""Entry point for Jarvis <-> LibreOffice Writer voice control.

process_word_command(text) is the module's whole public surface for
actually running a command: ensure the bridge process is up -> parse ->
send -> speak the result. register_commands(dispatcher) wires exactly one
command ("word_command", a raw-text param) into the shared dispatcher, same
reasoning as modules/blender_control/dispatcher.py's register_commands
docstring — one generic command lets the global AI intent_classifier route
any Writer-flavored utterance here with a single candidate, and this
module's own command_parser.py turns the raw text into a specific action.
"""

from __future__ import annotations

from typing import Any

from core.dispatcher import CommandDispatcher
from core.logger import get_logger
from modules.office_writer import command_parser
from modules.office_writer.bridge_client import OfficeWriterUnavailableError, office_writer_bridge_client

logger = get_logger(__name__)

_UNAVAILABLE_MESSAGE = "Не удалось подключиться к LibreOffice Writer, попробуй ещё раз через пару секунд."


def _format_headings(data: dict[str, Any]) -> str:
    headings = data.get("headings") or []
    if not headings:
        return "В документе нет заголовков."
    lines = [f"{'  ' * (heading['level'] - 1)}{heading['text']}" for heading in headings]
    return "Структура документа: " + "; ".join(lines)


def _success_message(action: str, params: dict[str, Any], data: dict[str, Any]) -> str:
    if action == "open_document":
        return f"Открыт {data.get('opened', 'документ')}"
    if action == "save_document":
        return "Документ сохранён"
    if action == "close_document":
        return "Документ закрыт"
    if action == "undo":
        return "Действие отменено"
    if action == "redo":
        return "Действие повторено"
    if action in ("insert_text", "replace_selection"):
        return "Готово"
    if action == "delete_selection":
        return "Выделенное удалено"
    if action == "set_format":
        return "Форматирование применено"
    if action == "insert_heading":
        return "Заголовок добавлен"
    if action == "list_headings":
        return _format_headings(data)
    if action == "insert_list":
        return "Список добавлен"
    if action == "insert_page_break":
        return "Разрыв страницы вставлен"
    if action == "insert_table":
        return "Таблица вставлена"
    if action in ("table_insert_row", "table_insert_column"):
        return "Добавлено"
    if action in ("table_delete_row", "table_delete_column"):
        return "Удалено"
    return "Готово."


async def process_word_command(text: str) -> str:
    """1. parse `text` (rule-based, then AI structuring as a fallback);
    2. make sure the bridge process is up, launching it if needed; 3. send
    the command (its own "open_document" handler launches soffice itself
    if it isn't running yet); 4. return a short Russian sentence for TTS
    describing what happened. Never raises."""
    parsed = await command_parser.parse_command(text)
    if parsed is None:
        return "Не понял, что нужно сделать в Writer."

    try:
        await office_writer_bridge_client.ensure_bridge_running()
        response = await office_writer_bridge_client.send_command(parsed.action, parsed.params)
    except OfficeWriterUnavailableError as exc:
        logger.warning("Office Writer command '%s' failed: %s", parsed.action, exc)
        return _UNAVAILABLE_MESSAGE

    if response.get("status") != "success":
        message = response.get("message") or "неизвестная ошибка"
        logger.info("Office Writer rejected command '%s': %s", parsed.action, message)
        return message

    data = response.get("data") or {}
    return _success_message(parsed.action, parsed.params, data)


async def _handle_word_command(params: dict[str, Any]) -> dict[str, Any]:
    text = params.get("text")
    if not text:
        raise ValueError("Missing required parameter 'text'")
    message = await process_word_command(text)
    return {"message": message}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "word_command",
        _handle_word_command,
        dangerous=False,
        description=(
            "Управление текстовым редактором LibreOffice Writer голосом: открытие/сохранение/закрытие "
            "документа, вставка и замена текста, форматирование (жирный, курсив, подчёркивание, размер и "
            "цвет шрифта, выравнивание), заголовки, маркированные и нумерованные списки, таблицы (вставка, "
            "добавление и удаление строк/столбцов), разрыв страницы, отмена и повтор действия. "
            "Использовать при любом упоминании Word, Writer, LibreOffice или работы с текстовым документом "
            "(text — полная исходная фраза пользователя)."
        ),
    )
