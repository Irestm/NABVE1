"""Rule-based Russian voice -> LibreOffice Writer action parser.

Same shape as modules/figma_control/command_parser.py: cheap regex patterns
checked first, an AI-structuring pass as a fallback for anything that
doesn't match one of them (see _parse_with_ai below), scoped to this
module's own action vocabulary (KNOWN_ACTIONS) rather than the whole app's
command list.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from core.ai_adapter_chain import candidate_chain
from core.logger import get_logger

logger = get_logger(__name__)

# Kept in sync with office_bridge/writer_handlers.py's ACTIONS dispatch
# table — the two sides run in separate Python processes (system python3
# with pyuno vs. this backend's own venv) and can't share a literal import.
KNOWN_ACTIONS: frozenset[str] = frozenset(
    {
        "open_document",
        "save_document",
        "close_document",
        "undo",
        "redo",
        "insert_text",
        "replace_selection",
        "delete_selection",
        "set_format",
        "insert_heading",
        "list_headings",
        "insert_list",
        "insert_page_break",
        "insert_table",
        "table_insert_row",
        "table_insert_column",
        "table_delete_row",
        "table_delete_column",
    }
)

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)

# Same "match by stem, not full declined form" reasoning as
# modules/figma_control/command_parser.py's _COLOR_STEMS_RU — kept as its
# own small copy here rather than imported from that module: figma_control
# is a separate voice-controlled surface, not a shared dependency, and this
# app's convention is one module per feature rather than cross-module
# reuse for a 15-line lookup table.
_COLOR_STEMS_RU: dict[str, str] = {
    "красн": "FF0000",
    "зелен": "00FF00",
    "зелён": "00FF00",
    "син": "0000FF",
    "черн": "000000",
    "чёрн": "000000",
    "бел": "FFFFFF",
    "желт": "FFFF00",
    "жёлт": "FFFF00",
    "оранжев": "FFA500",
    "фиолетов": "800080",
    "серы": "808080",
    "сер": "808080",
}

_ALIGN_PHRASES_RU: dict[str, str] = {
    "по левому краю": "left",
    "слева": "left",
    "по правому краю": "right",
    "справа": "right",
    "по центру": "center",
    "по ширине": "justify",
}


@dataclass(frozen=True)
class ParsedWriterCommand:
    action: str
    params: dict[str, object]


def _extract_color(text: str) -> str | None:
    hex_match = re.search(r"#?([0-9a-fA-F]{6})\b", text)
    if hex_match:
        return hex_match.group(1).upper()
    for stem, hex_value in _COLOR_STEMS_RU.items():
        if re.search(rf"\b{stem}\w*", text):
            return hex_value
    return None


def _parse_set_format(text: str) -> ParsedWriterCommand | None:
    """A single utterance can carry several formatting cues at once
    ("сделай жирным и по центру"), so this scans for every cue independently
    rather than matching one pattern exclusively — unlike the other
    handlers below, which each own a distinct phrasing."""
    params: dict[str, object] = {}

    if re.search(r"\bжирн", text):
        params["bold"] = not re.search(r"(?:убери|сними|не)\s+\S*жирн", text)
    if re.search(r"\bкурсив", text):
        params["italic"] = not re.search(r"(?:убери|сними|не)\s+\S*курсив", text)
    if re.search(r"подчерк|подчёрк", text):
        params["underline"] = not re.search(r"(?:убери|сними|не)\s+\S*подчерк", text)

    for phrase, alignment in _ALIGN_PHRASES_RU.items():
        if phrase in text:
            params["align"] = alignment
            break

    size_match = re.search(r"размер(?:а)?\s+шрифта\s+(\d+)", text)
    if size_match:
        params["font_size"] = int(size_match.group(1))

    if re.search(r"цвет(?:а)?\s+текста|сделай\s+текст", text):
        color = _extract_color(text)
        if color:
            params["color"] = color

    if not params:
        return None
    return ParsedWriterCommand(action="set_format", params=params)


def _parse_with_patterns(text: str) -> ParsedWriterCommand | None:
    normalized = text.strip().lower().rstrip(".!")
    if not normalized:
        return None

    match = re.match(r"^(?:открой|создай)\s+(?:ворд|word|документ|вритер|writer)(?:\s+(.+))?$", normalized)
    if match:
        params: dict[str, object] = {}
        if match.group(1):
            params["path"] = match.group(1).strip()
        return ParsedWriterCommand(action="open_document", params=params)

    match = re.match(r"^сохрани(?:\s+документ|\s+файл)?\s+как\s+(.+)$", normalized)
    if match:
        return ParsedWriterCommand(action="save_document", params={"path": match.group(1).strip()})

    if re.match(r"^сохрани(?:\s+документ|\s+файл)?$", normalized):
        return ParsedWriterCommand(action="save_document", params={})

    match = re.match(r"^закрой\s+(?:документ|файл)(?:\s+(с сохранением|без сохранения))?$", normalized)
    if match:
        save = match.group(1) == "с сохранением"
        return ParsedWriterCommand(action="close_document", params={"save": save})

    if normalized in ("отмени", "отмена", "отмени действие"):
        return ParsedWriterCommand(action="undo", params={})
    if normalized in ("верни", "повтори", "верни действие"):
        return ParsedWriterCommand(action="redo", params={})

    match = re.match(r"^(?:вставь\s+текст|напечатай|напиши|введи\s+текст)\s+(.+)$", normalized)
    if match:
        return ParsedWriterCommand(action="insert_text", params={"content": match.group(1).strip()})

    match = re.match(r"^допиши\s+(.+)$", normalized)
    if match:
        return ParsedWriterCommand(
            action="insert_text", params={"content": match.group(1).strip(), "position": "end"}
        )

    match = re.match(r"^замени\s+(?:выделенное|выделение)\s+на\s+(.+)$", normalized)
    if match:
        return ParsedWriterCommand(action="replace_selection", params={"content": match.group(1).strip()})

    if normalized in ("удали выделенное", "удали выделение"):
        return ParsedWriterCommand(action="delete_selection", params={})

    if normalized in ("вставь разрыв страницы", "новая страница", "разрыв страницы"):
        return ParsedWriterCommand(action="insert_page_break", params={})

    match = re.match(r"^вставь\s+таблицу\s+(\d+)\s*(?:на|x|х|\*)\s*(\d+)$", normalized)
    if match:
        return ParsedWriterCommand(
            action="insert_table", params={"rows": int(match.group(1)), "cols": int(match.group(2))}
        )

    match = re.match(r"^добавь\s+(?:строку|стро́ку)(?:\s+в\s+таблицу)?$", normalized)
    if match:
        return ParsedWriterCommand(action="table_insert_row", params={})

    match = re.match(r"^добавь\s+(?:столбец|колонку)(?:\s+в\s+таблицу)?$", normalized)
    if match:
        return ParsedWriterCommand(action="table_insert_column", params={})

    match = re.match(r"^удали\s+строку(?:\s+из\s+таблицы)?$", normalized)
    if match:
        return ParsedWriterCommand(action="table_delete_row", params={})

    match = re.match(r"^удали\s+(?:столбец|колонку)(?:\s+из\s+таблицы)?$", normalized)
    if match:
        return ParsedWriterCommand(action="table_delete_column", params={})

    match = re.match(r"^подзаголовок\s+(.+)$", normalized)
    if match:
        return ParsedWriterCommand(action="insert_heading", params={"text": match.group(1).strip(), "level": 2})

    match = re.match(r"^(?:вставь\s+)?заголовок(?:\s+уровня?\s+(\d+))?\s+(.+)$", normalized)
    if match:
        level = int(match.group(1)) if match.group(1) else 1
        return ParsedWriterCommand(action="insert_heading", params={"text": match.group(2).strip(), "level": level})

    if normalized in ("покажи структуру документа", "покажи заголовки", "структура документа"):
        return ParsedWriterCommand(action="list_headings", params={})

    match = re.match(r"^вставь\s+(нумерованный\s+|маркированный\s+)?список[:]?\s+(.+)$", normalized)
    if match:
        ordered = bool(match.group(1) and "нумер" in match.group(1))
        items = [item.strip() for item in re.split(r",|\s+и\s+", match.group(2)) if item.strip()]
        if items:
            return ParsedWriterCommand(action="insert_list", params={"items": items, "ordered": ordered})

    format_command = _parse_set_format(normalized)
    if format_command is not None:
        return format_command

    return None


def _build_ai_prompt(text: str) -> str:
    actions = ", ".join(sorted(KNOWN_ACTIONS))
    return (
        f"Пользователь дал голосовую команду для управления текстовым редактором LibreOffice Writer: "
        f"'{text}'. Вот список доступных действий: {actions}. Определи, какое действие имел в виду "
        "пользователь, и извлеки его параметры (path, content, position [cursor|start|end], save "
        "[true|false], bold/italic/underline [true|false], font_size, color [hex без решётки], "
        "align [left|right|center|justify], text, level [1-10], items [список строк], ordered "
        "[true|false], rows, cols, count — только те, что применимы к выбранному действию и упомянуты "
        "в фразе). Если команда не про управление Writer вообще или не подходит ни одно действие — "
        'верни null. Ответь ТОЛЬКО JSON-объектом без пояснений, строго в формате '
        '{"action": "<имя_или_null>", "params": {}}.'
    )


def _parse_ai_response(raw: str) -> ParsedWriterCommand | None:
    match = _JSON_OBJECT_PATTERN.search(raw)
    if not match:
        logger.warning("Office Writer AI command parsing returned no JSON object")
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("Office Writer AI command parsing returned invalid JSON")
        return None

    action = parsed.get("action")
    if action not in KNOWN_ACTIONS:
        return None
    raw_params = parsed.get("params")
    params = raw_params if isinstance(raw_params, dict) else {}
    return ParsedWriterCommand(action=action, params=params)


async def _parse_with_ai(text: str) -> ParsedWriterCommand | None:
    prompt = _build_ai_prompt(text)
    for adapter in candidate_chain(text):
        try:
            raw = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            logger.warning("Office Writer AI command parsing adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue
        parsed = _parse_ai_response(raw)
        if parsed is not None:
            return parsed
    return None


async def parse_command(text: str) -> ParsedWriterCommand | None:
    """Turn free voice text into a (action, params) pair the rest of the
    module can act on. Tries the fast literal patterns first, then falls
    back to AI structuring, same as modules/figma_control/command_parser.py.
    Returns None when neither path could make sense of it."""
    parsed = _parse_with_patterns(text)
    if parsed is not None:
        return parsed
    return await _parse_with_ai(text)
