"""Rule-based Russian voice -> LibreOffice Calc action parser.

Same shape as modules/office_writer/command_parser.py: cheap regex patterns
checked first, an AI-structuring pass as a fallback for anything that
doesn't match one of them, scoped to this module's own action vocabulary
(KNOWN_ACTIONS) rather than the whole app's command list. Calc commands
almost always name an explicit cell/range ("впиши в А1 сто", "формула в
Б2"), so — unlike Writer's cursor-relative phrasing — most patterns here
just capture a cell/range reference plus content.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from core.ai_adapter_chain import candidate_chain
from core.logger import get_logger

logger = get_logger(__name__)

# Kept in sync with office_bridge/calc_handlers.py's ACTIONS dispatch
# table — the two sides run in separate Python processes (system python3
# with pyuno vs. this backend's own venv) and can't share a literal import.
KNOWN_ACTIONS: frozenset[str] = frozenset(
    {
        "open_spreadsheet",
        "save_spreadsheet",
        "close_spreadsheet",
        "calc_undo",
        "calc_redo",
        "set_cell_value",
        "clear_range",
        "set_formula",
        "set_cell_format",
        "sheet_insert_row",
        "sheet_insert_column",
        "sheet_delete_row",
        "sheet_delete_column",
        "sheet_add",
        "sheet_rename",
        "sheet_switch",
    }
)

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)

# Same "match by stem, not full declined form" reasoning as
# modules/figma_control/command_parser.py's _COLOR_STEMS_RU / this app's
# other command_parser.py modules — kept as its own small copy per module
# rather than shared, matching this codebase's "one module per feature"
# convention over cross-module reuse for a short lookup table.
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

_CELL_REF = r"[A-Za-zА-Яа-яЁё]{1,3}\d{1,7}"
_RANGE_REF = rf"{_CELL_REF}(?::{_CELL_REF})?"

# Voice STT is likely to transliterate Latin column letters into Cyrillic
# look-alikes ("а1" instead of "a1") — normalize the handful that are
# visually identical in both alphabets before a cell/range reference is
# sent to the bridge, since LibreOffice only understands Latin column
# letters.
_CYRILLIC_TO_LATIN_LOOKALIKES = str.maketrans("АВЕКМНОРСТХаекморстух", "ABEKMHOPCTXaekmopctux")


def _normalize_cell_ref(ref: str) -> str:
    return ref.translate(_CYRILLIC_TO_LATIN_LOOKALIKES).upper()


@dataclass(frozen=True)
class ParsedExcelCommand:
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


def _parse_number_or_text(raw: str) -> object:
    normalized = raw.strip()
    try:
        return float(normalized.replace(",", "."))
    except ValueError:
        return normalized


def _parse_set_cell_format(text: str, range_ref: str) -> ParsedExcelCommand | None:
    """Mirrors modules/office_writer/command_parser.py's _parse_set_format:
    a single utterance can carry several formatting cues at once, so this
    scans for every cue independently."""
    params: dict[str, object] = {"range": _normalize_cell_ref(range_ref)}

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

    fill_match = re.search(r"залив\w*\s+(\S+)", text)
    if fill_match:
        color = _extract_color(fill_match.group(1)) or _extract_color(text)
        if color:
            params["fill_color"] = color
    elif re.search(r"цвет(?:а)?\s+текста|сделай\s+текст", text):
        color = _extract_color(text)
        if color:
            params["color"] = color

    if len(params) == 1:  # only "range" got set, no actual format cue matched
        return None
    return ParsedExcelCommand(action="set_cell_format", params=params)


def _parse_with_patterns(text: str) -> ParsedExcelCommand | None:
    normalized = text.strip().lower().rstrip(".!")
    if not normalized:
        return None

    match = re.match(r"^(?:открой|создай)\s+(?:эксель|excel|таблицу|калк|calc)(?:\s+(.+))?$", normalized)
    if match:
        params: dict[str, object] = {}
        if match.group(1):
            params["path"] = match.group(1).strip()
        return ParsedExcelCommand(action="open_spreadsheet", params=params)

    match = re.match(r"^сохрани(?:\s+таблицу|\s+файл)?\s+как\s+(.+)$", normalized)
    if match:
        return ParsedExcelCommand(action="save_spreadsheet", params={"path": match.group(1).strip()})

    if re.match(r"^сохрани(?:\s+таблицу|\s+файл)?$", normalized):
        return ParsedExcelCommand(action="save_spreadsheet", params={})

    match = re.match(r"^закрой\s+(?:таблицу|файл)(?:\s+(с сохранением|без сохранения))?$", normalized)
    if match:
        save = match.group(1) == "с сохранением"
        return ParsedExcelCommand(action="close_spreadsheet", params={"save": save})

    if normalized in ("отмени", "отмена", "отмени действие"):
        return ParsedExcelCommand(action="calc_undo", params={})
    if normalized in ("верни", "повтори", "верни действие"):
        return ParsedExcelCommand(action="calc_redo", params={})

    match = re.match(
        rf"^(?:впиши|напиши|введи)\s+в\s+({_CELL_REF})\s+(.+)$", normalized, re.IGNORECASE
    )
    if match:
        return ParsedExcelCommand(
            action="set_cell_value",
            params={"cell": _normalize_cell_ref(match.group(1)), "value": _parse_number_or_text(match.group(2))},
        )

    match = re.match(rf"^(?:очисти|удали значение)\s+(?:ячейку|ячейки|диапазон)?\s*({_RANGE_REF})$", normalized, re.IGNORECASE)
    if match:
        return ParsedExcelCommand(action="clear_range", params={"range": _normalize_cell_ref(match.group(1))})

    match = re.match(
        rf"^(?:формула|вставь формулу)\s+в\s+({_CELL_REF})\s+(.+)$", normalized, re.IGNORECASE
    )
    if match:
        return ParsedExcelCommand(
            action="set_formula", params={"cell": _normalize_cell_ref(match.group(1)), "formula": match.group(2).strip()}
        )

    match = re.match(r"^добавь\s+строку(?:\s+(\d+))?$", normalized)
    if match and match.group(1):
        return ParsedExcelCommand(action="sheet_insert_row", params={"row": int(match.group(1))})

    match = re.match(r"^добавь\s+столбец\s+([A-Za-zА-Яа-яЁё]{1,3})$", normalized, re.IGNORECASE)
    if match:
        return ParsedExcelCommand(action="sheet_insert_column", params={"column": _normalize_cell_ref(match.group(1))})

    match = re.match(r"^удали\s+строку\s+(\d+)$", normalized)
    if match:
        return ParsedExcelCommand(action="sheet_delete_row", params={"row": int(match.group(1))})

    match = re.match(r"^удали\s+столбец\s+([A-Za-zА-Яа-яЁё]{1,3})$", normalized, re.IGNORECASE)
    if match:
        return ParsedExcelCommand(action="sheet_delete_column", params={"column": _normalize_cell_ref(match.group(1))})

    match = re.match(r"^добавь\s+лист(?:\s+(?:с\s+именем|по\s+имени|назови\w*)\s+(.+))?$", normalized)
    if match:
        params = {}
        if match.group(1):
            params["name"] = match.group(1).strip()
        return ParsedExcelCommand(action="sheet_add", params=params)

    match = re.match(r"^переименуй\s+лист(?:\s+(.+?))?\s+в\s+(.+)$", normalized)
    if match:
        params = {"new_name": match.group(2).strip()}
        if match.group(1):
            params["old_name"] = match.group(1).strip()
        return ParsedExcelCommand(action="sheet_rename", params=params)

    match = re.match(r"^(?:перейди на лист|открой лист|переключись на лист)\s+(.+)$", normalized)
    if match:
        return ParsedExcelCommand(action="sheet_switch", params={"name": match.group(1).strip()})

    # Two phrasings for the same intent: "сделай А1 жирным" (cell ref right
    # after the verb) and "сделай ячейку А1:Б5 жирной" (explicit "ячейку"
    # word, needed when the range comes later in a longer sentence).
    direct_match = re.match(rf"^сделай\s+({_RANGE_REF})\s+(.+)$", normalized, re.IGNORECASE)
    if direct_match:
        format_command = _parse_set_cell_format(normalized, direct_match.group(1))
        if format_command is not None:
            return format_command

    format_match = re.match(rf"^(.*)\bячейк\w*\s+({_RANGE_REF})\b(.*)$", normalized)
    if format_match:
        format_command = _parse_set_cell_format(normalized, format_match.group(2))
        if format_command is not None:
            return format_command

    return None


def _build_ai_prompt(text: str) -> str:
    actions = ", ".join(sorted(KNOWN_ACTIONS))
    return (
        f"Пользователь дал голосовую команду для управления табличным редактором LibreOffice Calc: "
        f"'{text}'. Вот список доступных действий: {actions}. Определи, какое действие имел в виду "
        "пользователь, и извлеки его параметры (path, save [true|false], cell [например A1], "
        "range [например A1:B10], value [текст или число], formula [без знака = в начале необязательно], "
        "bold/italic/underline [true|false], font_size, color/fill_color [hex без решётки], "
        "align [left|right|center|justify], row [номер строки], column [буква столбца], count, name, "
        "old_name, new_name — только те, что применимы к выбранному действию и упомянуты в фразе). Если "
        "команда не про управление Calc/Excel вообще или не подходит ни одно действие — верни null. "
        'Ответь ТОЛЬКО JSON-объектом без пояснений, строго в формате {"action": "<имя_или_null>", "params": {}}.'
    )


def _parse_ai_response(raw: str) -> ParsedExcelCommand | None:
    match = _JSON_OBJECT_PATTERN.search(raw)
    if not match:
        logger.warning("Office Excel AI command parsing returned no JSON object")
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("Office Excel AI command parsing returned invalid JSON")
        return None

    action = parsed.get("action")
    if action not in KNOWN_ACTIONS:
        return None
    raw_params = parsed.get("params")
    params = raw_params if isinstance(raw_params, dict) else {}
    return ParsedExcelCommand(action=action, params=params)


async def _parse_with_ai(text: str) -> ParsedExcelCommand | None:
    prompt = _build_ai_prompt(text)
    for adapter in candidate_chain(text):
        try:
            raw = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            logger.warning("Office Excel AI command parsing adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue
        parsed = _parse_ai_response(raw)
        if parsed is not None:
            return parsed
    return None


async def parse_command(text: str) -> ParsedExcelCommand | None:
    """Turn free voice text into a (action, params) pair the rest of the
    module can act on. Tries the fast literal patterns first, then falls
    back to AI structuring, same as modules/office_writer/command_parser.py.
    Returns None when neither path could make sense of it."""
    parsed = _parse_with_patterns(text)
    if parsed is not None:
        return parsed
    return await _parse_with_ai(text)
