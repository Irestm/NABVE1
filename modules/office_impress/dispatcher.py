"""Entry point for Jarvis <-> LibreOffice Impress voice control.

process_impress_command(text) is the module's whole public surface for
actually running a command: ensure the shared office bridge process is up ->
parse -> send -> speak the result. register_commands(dispatcher) wires
exactly one command ("impress_command", a raw-text param) into the shared
dispatcher — same reasoning as modules/office_writer/dispatcher.py's
register_commands docstring.
"""

from __future__ import annotations

from typing import Any

from core.dispatcher import CommandDispatcher
from core.logger import get_logger
from modules.office_impress import command_parser
from modules.office_impress.bridge_client import OfficeImpressUnavailableError, office_impress_bridge_client

logger = get_logger(__name__)

_UNAVAILABLE_MESSAGE = "Не удалось подключиться к LibreOffice Impress, попробуй ещё раз через пару секунд."


def _success_message(action: str, params: dict[str, Any], data: dict[str, Any]) -> str:
    if action == "open_presentation":
        return f"Открыт {data.get('opened', 'файл')}"
    if action == "save_presentation":
        return "Презентация сохранена"
    if action == "close_presentation":
        return "Презентация закрыта"
    if action == "impress_undo":
        return "Действие отменено"
    if action == "impress_redo":
        return "Действие повторено"
    if action == "add_slide":
        return f"Добавлен слайд {data.get('index', '')}".strip()
    if action == "delete_slide":
        return "Слайд удалён"
    if action == "duplicate_slide":
        return "Слайд продублирован"
    if action == "go_to_slide":
        return "Переключено на другой слайд"
    if action == "set_slide_title":
        return "Заголовок обновлён"
    if action == "set_slide_body":
        return "Текст слайда обновлён"
    if action == "set_slide_layout":
        return "Макет слайда изменён"
    if action == "set_slide_text_format":
        return "Форматирование применено"
    return "Готово."


async def process_impress_command(text: str) -> str:
    """1. parse `text` (rule-based, then AI structuring as a fallback);
    2. make sure the shared office bridge process is up, launching it if
    needed; 3. send the command (its own "open_presentation" handler
    launches soffice itself if it isn't running yet); 4. return a short
    Russian sentence for TTS describing what happened. Never raises."""
    parsed = await command_parser.parse_command(text)
    if parsed is None:
        return "Не понял, что нужно сделать в Impress."

    try:
        await office_impress_bridge_client.ensure_bridge_running()
        response = await office_impress_bridge_client.send_command(parsed.action, parsed.params)
    except OfficeImpressUnavailableError as exc:
        logger.warning("Office Impress command '%s' failed: %s", parsed.action, exc)
        return _UNAVAILABLE_MESSAGE

    if response.get("status") != "success":
        message = response.get("message") or "неизвестная ошибка"
        logger.info("Office Impress rejected command '%s': %s", parsed.action, message)
        return message

    data = response.get("data") or {}
    return _success_message(parsed.action, parsed.params, data)


async def _handle_impress_command(params: dict[str, Any]) -> dict[str, Any]:
    text = params.get("text")
    if not text:
        raise ValueError("Missing required parameter 'text'")
    message = await process_impress_command(text)
    return {"message": message}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "impress_command",
        _handle_impress_command,
        dangerous=False,
        description=(
            "Управление редактором презентаций LibreOffice Impress голосом: открытие/сохранение/закрытие "
            "презентации, добавление/удаление/дублирование слайдов, переход к слайду, заголовок и текст "
            "слайда, макет слайда, форматирование текста (жирный, курсив, подчёркивание, размер и цвет "
            "шрифта, выравнивание), отмена и повтор действия. Использовать при любом упоминании PowerPoint, "
            "Impress, LibreOffice или работы со слайдами/презентацией (text — полная исходная фраза "
            "пользователя)."
        ),
    )
