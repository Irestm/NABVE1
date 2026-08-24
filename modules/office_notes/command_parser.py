"""Rule-based Russian voice -> notebook action parser.

NABVE1's "OneNote" slice of the office-suite task — LibreOffice has no
notebook/section/page application, so this module is a semantic skin over
Writer's own heading hierarchy (see modules/office_notes/dispatcher.py,
which maps these actions onto office_bridge/writer_handlers.py's existing
insert_heading/insert_text/list_headings/... — no new UNO handlers needed
for this module). Same shape as this app's other office command_parser.py
modules otherwise: cheap regex patterns first, AI-structuring fallback,
scoped to this module's own action vocabulary (KNOWN_ACTIONS) — which is
its own small set of notebook-flavored verbs, not Writer's.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from core.ai_adapter_chain import candidate_chain
from core.logger import get_logger

logger = get_logger(__name__)

KNOWN_ACTIONS: frozenset[str] = frozenset(
    {
        "open_notebook",
        "save_notebook",
        "close_notebook",
        "undo",
        "redo",
        "create_section",
        "create_page",
        "write_text",
        "list_structure",
    }
)

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True)
class ParsedNotesCommand:
    action: str
    params: dict[str, object]


def _parse_with_patterns(text: str) -> ParsedNotesCommand | None:
    normalized = text.strip().lower().rstrip(".!")
    if not normalized:
        return None

    match = re.match(r"^(?:открой|создай)\s+блокнот\s+(.+)$", normalized)
    if match:
        return ParsedNotesCommand(action="open_notebook", params={"name": match.group(1).strip()})

    if re.match(r"^сохрани\s+блокнот$", normalized):
        return ParsedNotesCommand(action="save_notebook", params={})

    match = re.match(r"^закрой\s+блокнот(?:\s+(с сохранением|без сохранения))?$", normalized)
    if match:
        return ParsedNotesCommand(action="close_notebook", params={"save": match.group(1) == "с сохранением"})

    if normalized in ("отмени", "отмена", "отмени действие"):
        return ParsedNotesCommand(action="undo", params={})
    if normalized in ("верни", "повтори", "верни действие"):
        return ParsedNotesCommand(action="redo", params={})

    match = re.match(r"^создай\s+раздел\s+(.+)$", normalized)
    if match:
        return ParsedNotesCommand(action="create_section", params={"text": match.group(1).strip()})

    match = re.match(r"^создай\s+страницу\s+(.+)$", normalized)
    if match:
        return ParsedNotesCommand(action="create_page", params={"text": match.group(1).strip()})

    match = re.match(r"^(?:напиши|допиши|запиши)\s+(.+)$", normalized)
    if match:
        return ParsedNotesCommand(action="write_text", params={"content": match.group(1).strip()})

    if normalized in (
        "покажи блокнот",
        "покажи структуру блокнота",
        "какие разделы",
        "какие есть разделы",
        "покажи разделы",
    ):
        return ParsedNotesCommand(action="list_structure", params={})

    return None


def _build_ai_prompt(text: str) -> str:
    actions = ", ".join(sorted(KNOWN_ACTIONS))
    return (
        f"Пользователь дал голосовую команду для управления голосовым блокнотом заметок (аналог "
        f"OneNote — на самом деле обычный текстовый документ с иерархией заголовков): '{text}'. Вот "
        f"список доступных действий: {actions}. Определи, какое действие имел в виду пользователь, и "
        "извлеки его параметры (name — имя блокнота для open_notebook, save [true|false], text — текст "
        "заголовка раздела/страницы, content — текст для дописывания — только те, что применимы к "
        "выбранному действию и упомянуты в фразе). Если команда не про блокнот/заметки вообще или не "
        'подходит ни одно действие — верни null. Ответь ТОЛЬКО JSON-объектом без пояснений, строго в '
        'формате {"action": "<имя_или_null>", "params": {}}.'
    )


def _parse_ai_response(raw: str) -> ParsedNotesCommand | None:
    match = _JSON_OBJECT_PATTERN.search(raw)
    if not match:
        logger.warning("Office Notes AI command parsing returned no JSON object")
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("Office Notes AI command parsing returned invalid JSON")
        return None

    action = parsed.get("action")
    if action not in KNOWN_ACTIONS:
        return None
    raw_params = parsed.get("params")
    params = raw_params if isinstance(raw_params, dict) else {}
    return ParsedNotesCommand(action=action, params=params)


async def _parse_with_ai(text: str) -> ParsedNotesCommand | None:
    prompt = _build_ai_prompt(text)
    for adapter in candidate_chain(text):
        try:
            raw = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            logger.warning("Office Notes AI command parsing adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue
        parsed = _parse_ai_response(raw)
        if parsed is not None:
            return parsed
    return None


async def parse_command(text: str) -> ParsedNotesCommand | None:
    """Turn free voice text into a (action, params) pair the rest of the
    module can act on. Tries the fast literal patterns first, then falls
    back to AI structuring, same as this app's other command parsers.
    Returns None when neither path could make sense of it."""
    parsed = _parse_with_patterns(text)
    if parsed is not None:
        return parsed
    return await _parse_with_ai(text)
