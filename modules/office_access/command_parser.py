"""Rule-based Russian voice -> LibreOffice Base action parser.

Same shape as this app's other office command_parser.py modules: cheap
regex patterns checked first, an AI-structuring pass as a fallback, scoped
to this module's own action vocabulary (KNOWN_ACTIONS). Database commands
are inherently more structured than "insert this text" — voice phrasing
here leans on explicit connector words ("где", "равно", "с колонками")
rather than natural free-form sentences, since the alternative is trying to
parse arbitrary SQL out of speech, which the AI-structuring fallback is a
much better fit for anyway.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from core.ai_adapter_chain import candidate_chain
from core.logger import get_logger

logger = get_logger(__name__)

# Kept in sync with office_bridge/access_handlers.py's ACTIONS dispatch
# table — the two sides run in separate Python processes (system python3
# with pyuno vs. this backend's own venv) and can't share a literal import.
KNOWN_ACTIONS: frozenset[str] = frozenset(
    {
        "open_database",
        "save_database",
        "close_database",
        "create_table",
        "delete_table",
        "list_tables",
        "insert_row",
        "update_rows",
        "delete_rows",
        "list_rows",
    }
)

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)

_COLUMN_TYPE_WORDS: dict[str, str] = {
    "текст": "text",
    "число": "number",
    "целое": "number",
    "дробное": "decimal",
    "дата": "date",
    "булево": "boolean",
    "логическое": "boolean",
}

DEFAULT_LIST_LIMIT = 10


@dataclass(frozen=True)
class ParsedAccessCommand:
    action: str
    params: dict[str, object]


def _parse_value(raw: str) -> object:
    text = raw.strip().strip("'\"")
    lowered = text.lower()
    if lowered in ("да", "истина", "true"):
        return True
    if lowered in ("нет", "ложь", "false"):
        return False
    try:
        if "." in text or "," in text:
            return float(text.replace(",", "."))
        return int(text)
    except ValueError:
        return text


def _parse_field_value_pairs(text: str) -> dict[str, object] | None:
    """Splits "поле равно значение, поле2: значение2" into
    {"поле": значение, "поле2": значение2}. Each piece must use "равно" or
    ":" as the field/value separator — see this module's own docstring for
    why voice phrasing here is deliberately this rigid."""
    pairs: dict[str, object] = {}
    for piece in text.split(","):
        piece = piece.strip()
        if not piece:
            continue
        match = re.match(r"^(.+?)\s*(?:равно|:)\s*(.+)$", piece)
        if not match:
            return None
        pairs[match.group(1).strip()] = _parse_value(match.group(2))
    return pairs or None


def _parse_columns(text: str) -> list[dict[str, str]] | None:
    """Splits "имя текст, возраст число" into
    [{"name": "имя", "type": "text"}, {"name": "возраст", "type": "number"}]
    — the last word of each comma-separated piece is the type word (looked
    up in _COLUMN_TYPE_WORDS), everything before it is the column name."""
    columns: list[dict[str, str]] = []
    for piece in text.split(","):
        piece = piece.strip()
        if not piece:
            continue
        tokens = piece.rsplit(maxsplit=1)
        if len(tokens) != 2:
            return None
        name, type_word = tokens
        column_type = _COLUMN_TYPE_WORDS.get(type_word.lower())
        if column_type is None:
            return None
        columns.append({"name": name.strip(), "type": column_type})
    return columns or None


def _parse_with_patterns(text: str) -> ParsedAccessCommand | None:
    normalized = text.strip().lower().rstrip(".!")
    if not normalized:
        return None

    match = re.match(r"^открой\s+баз[ауы](?:\s+данных)?\s+(.+)$", normalized)
    if match:
        return ParsedAccessCommand(action="open_database", params={"path": match.group(1).strip()})

    if re.match(r"^сохрани\s+баз[ауы](?:\s+данных)?$", normalized):
        return ParsedAccessCommand(action="save_database", params={})

    match = re.match(r"^закрой\s+баз[ауы](?:\s+данных)?(?:\s+(с сохранением|без сохранения))?$", normalized)
    if match:
        return ParsedAccessCommand(action="close_database", params={"save": match.group(1) == "с сохранением"})

    match = re.match(r"^создай\s+таблицу\s+(\S+)\s+с\s+колонками\s+(.+)$", normalized)
    if match:
        columns = _parse_columns(match.group(2))
        if columns is not None:
            return ParsedAccessCommand(action="create_table", params={"name": match.group(1), "columns": columns})

    match = re.match(r"^удали\s+таблицу\s+(\S+)$", normalized)
    if match:
        return ParsedAccessCommand(action="delete_table", params={"name": match.group(1)})

    if normalized in ("покажи таблицы", "какие есть таблицы", "какие таблицы"):
        return ParsedAccessCommand(action="list_tables", params={})

    match = re.match(r"^добавь\s+(?:в\s+таблицу|запись\s+в)\s+(\S+)[:]?\s+(.+)$", normalized)
    if match:
        values = _parse_field_value_pairs(match.group(2))
        if values is not None:
            return ParsedAccessCommand(action="insert_row", params={"table": match.group(1), "values": values})

    match = re.match(
        r"^(?:измени|обнови)\s+(?:в\s+таблице\s+)?([^\s,]+)\s*,?\s*где\s+(.+?)\s+равно\s+(.+?)\s*,\s*поставь\s+(.+?)\s+равно\s+(.+)$",
        normalized,
    )
    if match:
        table, where_column, where_value, set_column, set_value = match.groups()
        return ParsedAccessCommand(
            action="update_rows",
            params={
                "table": table,
                "where_column": where_column.strip(),
                "where_value": _parse_value(where_value),
                "set": {set_column.strip(): _parse_value(set_value)},
            },
        )

    match = re.match(r"^удали\s+(?:из\s+таблицы\s+)?([^\s,]+)\s*,?\s*где\s+(.+?)\s+равно\s+(.+)$", normalized)
    if match:
        table, where_column, where_value = match.groups()
        return ParsedAccessCommand(
            action="delete_rows",
            params={"table": table, "where_column": where_column.strip(), "where_value": _parse_value(where_value)},
        )

    match = re.match(r"^покажи(?:\s+(\d+))?\s+запис(?:и|ей)\s+из\s+таблицы\s+(\S+)$", normalized)
    if match:
        params: dict[str, object] = {"table": match.group(2)}
        if match.group(1):
            params["limit"] = int(match.group(1))
        return ParsedAccessCommand(action="list_rows", params=params)

    return None


def _build_ai_prompt(text: str) -> str:
    actions = ", ".join(sorted(KNOWN_ACTIONS))
    return (
        f"Пользователь дал голосовую команду для управления базой данных LibreOffice Base: '{text}'. "
        f"Вот список доступных действий: {actions}. Определи, какое действие имел в виду пользователь, и "
        "извлеки его параметры (path, save [true|false], name — имя таблицы, columns — список объектов "
        '{"name": ..., "type": "text|number|decimal|date|boolean"} для create_table, table — имя таблицы, '
        "values — объект поле:значение для insert_row, set — объект поле:значение для update_rows, "
        "where_column и where_value — условие для update_rows/delete_rows, limit — сколько записей "
        "показать для list_rows — только те, что применимы к выбранному действию и упомянуты в фразе). "
        "Если команда не про управление базой данных вообще или не подходит ни одно действие — верни "
        'null. Ответь ТОЛЬКО JSON-объектом без пояснений, строго в формате {"action": "<имя_или_null>", '
        '"params": {}}.'
    )


def _parse_ai_response(raw: str) -> ParsedAccessCommand | None:
    match = _JSON_OBJECT_PATTERN.search(raw)
    if not match:
        logger.warning("Office Access AI command parsing returned no JSON object")
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("Office Access AI command parsing returned invalid JSON")
        return None

    action = parsed.get("action")
    if action not in KNOWN_ACTIONS:
        return None
    raw_params = parsed.get("params")
    params = raw_params if isinstance(raw_params, dict) else {}
    return ParsedAccessCommand(action=action, params=params)


async def _parse_with_ai(text: str) -> ParsedAccessCommand | None:
    prompt = _build_ai_prompt(text)
    for adapter in candidate_chain(text):
        try:
            raw = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            logger.warning("Office Access AI command parsing adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue
        parsed = _parse_ai_response(raw)
        if parsed is not None:
            return parsed
    return None


async def parse_command(text: str) -> ParsedAccessCommand | None:
    """Turn free voice text into a (action, params) pair the rest of the
    module can act on. Tries the fast literal patterns first, then falls
    back to AI structuring, same as this app's other command parsers.
    Returns None when neither path could make sense of it."""
    parsed = _parse_with_patterns(text)
    if parsed is not None:
        return parsed
    return await _parse_with_ai(text)
