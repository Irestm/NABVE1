"""Rule-based Russian voice -> LibreOffice Impress action parser.

Same shape as modules/office_writer/ and modules/office_excel/'s
command_parser.py: cheap regex patterns checked first, an AI-structuring
pass as a fallback, scoped to this module's own action vocabulary
(KNOWN_ACTIONS). Like Excel, most patterns here name an explicit target
(slide number) rather than relying on a cursor.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from core.ai_adapter_chain import candidate_chain
from core.logger import get_logger

logger = get_logger(__name__)

# Kept in sync with office_bridge/impress_handlers.py's ACTIONS dispatch
# table — the two sides run in separate Python processes (system python3
# with pyuno vs. this backend's own venv) and can't share a literal import.
KNOWN_ACTIONS: frozenset[str] = frozenset(
    {
        "open_presentation",
        "save_presentation",
        "close_presentation",
        "impress_undo",
        "impress_redo",
        "add_slide",
        "delete_slide",
        "duplicate_slide",
        "go_to_slide",
        "set_slide_title",
        "set_slide_body",
        "set_slide_layout",
        "set_slide_text_format",
    }
)

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)

# Same "match by stem, not full declined form" reasoning as this app's other
# command_parser.py modules — kept as its own small copy per module.
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
class ParsedImpressCommand:
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


def _parse_text_format(text: str, target: str) -> ParsedImpressCommand | None:
    """Mirrors modules/office_writer/command_parser.py's _parse_set_format
    and modules/office_excel/command_parser.py's _parse_set_cell_format: a
    single utterance can carry several formatting cues at once, so this
    scans for every cue independently."""
    params: dict[str, object] = {"target": target}

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

    if len(params) == 1:  # only "target" got set, no actual format cue matched
        return None
    return ParsedImpressCommand(action="set_slide_text_format", params=params)


def _parse_with_patterns(text: str) -> ParsedImpressCommand | None:
    normalized = text.strip().lower().rstrip(".!")
    if not normalized:
        return None

    match = re.match(
        r"^(?:открой|создай)\s+(?:презентацию|powerpoint|поверпоинт|импресс|impress)(?:\s+(.+))?$", normalized
    )
    if match:
        params: dict[str, object] = {}
        if match.group(1):
            params["path"] = match.group(1).strip()
        return ParsedImpressCommand(action="open_presentation", params=params)

    match = re.match(r"^сохрани(?:\s+презентацию|\s+файл)?\s+как\s+(.+)$", normalized)
    if match:
        return ParsedImpressCommand(action="save_presentation", params={"path": match.group(1).strip()})

    if re.match(r"^сохрани(?:\s+презентацию|\s+файл)?$", normalized):
        return ParsedImpressCommand(action="save_presentation", params={})

    match = re.match(r"^закрой\s+(?:презентацию|файл)(?:\s+(с сохранением|без сохранения))?$", normalized)
    if match:
        save = match.group(1) == "с сохранением"
        return ParsedImpressCommand(action="close_presentation", params={"save": save})

    if normalized in ("отмени", "отмена", "отмени действие"):
        return ParsedImpressCommand(action="impress_undo", params={})
    if normalized in ("верни", "повтори", "верни действие"):
        return ParsedImpressCommand(action="impress_redo", params={})

    match = re.match(r"^добавь\s+слайд(?:\s+(?:номер\s+)?(\d+))?$", normalized)
    if match:
        params = {}
        if match.group(1):
            params["index"] = int(match.group(1))
        return ParsedImpressCommand(action="add_slide", params=params)

    match = re.match(r"^удали\s+слайд\s+(\d+)$", normalized)
    if match:
        return ParsedImpressCommand(action="delete_slide", params={"index": int(match.group(1))})

    match = re.match(r"^(?:дублируй|скопируй)\s+слайд\s+(\d+)$", normalized)
    if match:
        return ParsedImpressCommand(action="duplicate_slide", params={"index": int(match.group(1))})

    match = re.match(r"^(?:перейди на слайд|открой слайд|покажи слайд)\s+(\d+)$", normalized)
    if match:
        return ParsedImpressCommand(action="go_to_slide", params={"index": int(match.group(1))})

    match = re.match(r"^(?:заголовок слайда|заголовок)(?:\s+(\d+))?\s*[:]?\s+(.+)$", normalized)
    if match:
        params = {"text": match.group(2).strip()}
        if match.group(1):
            params["index"] = int(match.group(1))
        return ParsedImpressCommand(action="set_slide_title", params=params)

    match = re.match(r"^(?:текст слайда|содержимое слайда|тело слайда)(?:\s+(\d+))?\s*[:]?\s+(.+)$", normalized)
    if match:
        items = [item.strip() for item in re.split(r",|\s+и\s+", match.group(2)) if item.strip()]
        params = {"items": items} if len(items) > 1 else {"text": match.group(2).strip()}
        if match.group(1):
            params["index"] = int(match.group(1))
        return ParsedImpressCommand(action="set_slide_body", params=params)

    match = re.match(r"^сделай\s+слайд(?:\s+(\d+))?\s+пустым$", normalized)
    if match:
        params = {"layout": "blank"}
        if match.group(1):
            params["index"] = int(match.group(1))
        return ParsedImpressCommand(action="set_slide_layout", params=params)

    match = re.match(r"^сделай\s+заголовок(?:\s+слайда\s+(\d+))?\s+(.+)$", normalized)
    if match:
        format_command = _parse_text_format(normalized, "title")
        if format_command is not None:
            if match.group(1):
                format_command.params["index"] = int(match.group(1))
            return format_command

    match = re.match(r"^сделай\s+текст(?:\s+слайда\s+(\d+))?\s+(.+)$", normalized)
    if match:
        format_command = _parse_text_format(normalized, "body")
        if format_command is not None:
            if match.group(1):
                format_command.params["index"] = int(match.group(1))
            return format_command

    return None


def _build_ai_prompt(text: str) -> str:
    actions = ", ".join(sorted(KNOWN_ACTIONS))
    return (
        f"Пользователь дал голосовую команду для управления редактором презентаций LibreOffice Impress: "
        f"'{text}'. Вот список доступных действий: {actions}. Определи, какое действие имел в виду "
        "пользователь, и извлеки его параметры (path, save [true|false], index [номер слайда, с 1], "
        "text, items [список строк для маркированного текста], target [title|body], layout "
        "[title_content|blank], bold/italic/underline [true|false], font_size, color [hex без решётки], "
        "align [left|right|center|justify] — только те, что применимы к выбранному действию и упомянуты "
        "в фразе). Если команда не про управление Impress/PowerPoint вообще или не подходит ни одно "
        'действие — верни null. Ответь ТОЛЬКО JSON-объектом без пояснений, строго в формате '
        '{"action": "<имя_или_null>", "params": {}}.'
    )


def _parse_ai_response(raw: str) -> ParsedImpressCommand | None:
    match = _JSON_OBJECT_PATTERN.search(raw)
    if not match:
        logger.warning("Office Impress AI command parsing returned no JSON object")
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("Office Impress AI command parsing returned invalid JSON")
        return None

    action = parsed.get("action")
    if action not in KNOWN_ACTIONS:
        return None
    raw_params = parsed.get("params")
    params = raw_params if isinstance(raw_params, dict) else {}
    return ParsedImpressCommand(action=action, params=params)


async def _parse_with_ai(text: str) -> ParsedImpressCommand | None:
    prompt = _build_ai_prompt(text)
    for adapter in candidate_chain(text):
        try:
            raw = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            logger.warning("Office Impress AI command parsing adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue
        parsed = _parse_ai_response(raw)
        if parsed is not None:
            return parsed
    return None


async def parse_command(text: str) -> ParsedImpressCommand | None:
    """Turn free voice text into a (action, params) pair the rest of the
    module can act on. Tries the fast literal patterns first, then falls
    back to AI structuring, same as this app's other office command
    parsers. Returns None when neither path could make sense of it."""
    parsed = _parse_with_patterns(text)
    if parsed is not None:
        return parsed
    return await _parse_with_ai(text)
