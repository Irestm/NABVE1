"""Entry point for Jarvis's voice notebook (NABVE1's "OneNote" slice of the
office-suite task — see AGENT_NOTES.md: LibreOffice has no notebook/section/
page application, so a "notebook" here is just a Writer .odt file under
core.config.NOTES_DIR, and "sections"/"pages" are Heading 1/Heading 2
paragraphs — see office_bridge/writer_handlers.py's list_headings). This
module adds no new UNO handlers of its own: every action below is
translated into an existing Writer bridge action (insert_heading/
insert_text/list_headings/...) and sent through
modules.office_writer.bridge_client's already-registered bridge client
rather than a duplicate one, since there's no new action vocabulary or
document type here to justify one.

process_notes_command(text) is the module's whole public surface;
register_commands(dispatcher) wires one command ("notes_command", a
raw-text param) into the shared dispatcher, same reasoning as this app's
other voice-controlled office modules.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.config import NOTES_DIR
from core.dispatcher import CommandDispatcher
from core.logger import get_logger
from modules.office_notes import command_parser
from modules.office_writer.bridge_client import OfficeWriterUnavailableError, office_writer_bridge_client

logger = get_logger(__name__)

_UNAVAILABLE_MESSAGE = "Не удалось подключиться к блокноту, попробуй ещё раз через пару секунд."

# Notebook names come from voice/AI-parsed text and get turned directly
# into a filename under NOTES_DIR — anything outside this small safe set
# (letters incl. Cyrillic, digits, spaces, dash, underscore, dot) is
# stripped so a stray "/" or ".." in a misheard name can't escape NOTES_DIR
# or collide with an unintended path.
_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w\-. а-яёА-ЯЁ]", re.UNICODE)


def _notebook_path(name: str) -> Path:
    safe_name = _UNSAFE_FILENAME_CHARS.sub("_", name.strip()) or "блокнот"
    return NOTES_DIR / f"{safe_name}.odt"


def _format_structure(data: dict[str, Any]) -> str:
    headings = data.get("headings") or []
    if not headings:
        return "В блокноте пока нет разделов."
    lines = [f"{'Раздел' if heading['level'] == 1 else 'Страница'}: {heading['text']}" for heading in headings]
    return "Структура блокнота: " + "; ".join(lines)


def _success_message(action: str, data: dict[str, Any]) -> str:
    if action == "open_notebook":
        return "Блокнот открыт"
    if action == "save_notebook":
        return "Блокнот сохранён"
    if action == "close_notebook":
        return "Блокнот закрыт"
    if action == "undo":
        return "Действие отменено"
    if action == "redo":
        return "Действие повторено"
    if action == "create_section":
        return "Раздел добавлен"
    if action == "create_page":
        return "Страница добавлена"
    if action == "write_text":
        return "Готово"
    if action == "list_structure":
        return _format_structure(data)
    return "Готово."


def _to_writer_command(parsed: command_parser.ParsedNotesCommand) -> tuple[str, dict[str, Any]]:
    """Translates one notebook-flavored action into the underlying Writer
    bridge action + params it actually runs as."""
    action, params = parsed.action, parsed.params
    if action == "open_notebook":
        return "open_document", {"path": str(_notebook_path(str(params["name"])))}
    if action == "save_notebook":
        return "save_document", {}
    if action == "close_notebook":
        return "close_document", {"save": bool(params.get("save"))}
    if action in ("undo", "redo"):
        return action, {}
    if action == "create_section":
        return "insert_heading", {"text": params["text"], "level": 1}
    if action == "create_page":
        return "insert_heading", {"text": params["text"], "level": 2}
    if action == "write_text":
        return "insert_text", {"content": params["content"], "position": "end"}
    if action == "list_structure":
        return "list_headings", {}
    raise ValueError(f"Unhandled notes action: {action}")


async def process_notes_command(text: str) -> str:
    """1. parse `text` (rule-based, then AI structuring as a fallback);
    2. translate the notebook-flavored action into the Writer bridge action
    it actually is; 3. ensure the shared office bridge process is up,
    launching it if needed; 4. send the command; 5. return a short Russian
    sentence for TTS describing what happened. Never raises."""
    parsed = await command_parser.parse_command(text)
    if parsed is None:
        return "Не понял, что нужно сделать с блокнотом."

    writer_action, writer_params = _to_writer_command(parsed)

    try:
        await office_writer_bridge_client.ensure_bridge_running()
        response = await office_writer_bridge_client.send_command(writer_action, writer_params)
    except OfficeWriterUnavailableError as exc:
        logger.warning("Office Notes command '%s' failed: %s", parsed.action, exc)
        return _UNAVAILABLE_MESSAGE

    if response.get("status") != "success":
        message = response.get("message") or "неизвестная ошибка"
        logger.info("Office Notes rejected command '%s': %s", parsed.action, message)
        return message

    data = response.get("data") or {}
    return _success_message(parsed.action, data)


async def _handle_notes_command(params: dict[str, Any]) -> dict[str, Any]:
    text = params.get("text")
    if not text:
        raise ValueError("Missing required parameter 'text'")
    message = await process_notes_command(text)
    return {"message": message}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "notes_command",
        _handle_notes_command,
        dangerous=False,
        description=(
            "Голосовой блокнот заметок (аналог OneNote — на деле обычный текстовый документ с "
            "разделами и страницами): открытие блокнота по имени, создание разделов и страниц, "
            "дописывание текста, просмотр структуры блокнота, сохранение и закрытие, отмена и повтор "
            "действия. Использовать при любом упоминании блокнота, заметок, OneNote, разделов/страниц "
            "заметок (text — полная исходная фраза пользователя)."
        ),
    )
