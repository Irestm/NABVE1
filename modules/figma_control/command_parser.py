from __future__ import annotations

import json
import re
from dataclasses import dataclass

from core.ai_adapter_chain import local_first_chain
from core.logger import get_logger

logger = get_logger(__name__)

# Kept in sync with figma_plugin/code.ts's HANDLERS map and
# modules/figma_control/screen_fallback.py's action set — this is the
# complete vocabulary either execution path can act on. Used to validate
# whatever the AI fallback (_parse_with_ai below) comes back with, so a
# hallucinated action name fails fast as "couldn't understand" instead of
# being forwarded to the plugin/fallback as-is.
KNOWN_ACTIONS: frozenset[str] = frozenset(
    {
        "create_rectangle",
        "create_text",
        "create_frame",
        "select_layer",
        "move_layer",
        "resize_layer",
        "change_color",
        "group_selection",
        "align",
        "delete_layer",
        "export_selection",
        "undo",
        "redo",
    }
)

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)

# Voice colour names -> hex, keyed by word STEM rather than the full
# nominative adjective: Russian adjectives decline by case/gender, and a
# spoken command is just as likely to say "покрась в красный" (accusative)
# as "сделай его красным" (instrumental) or "красная" (feminine) — matching
# only the exact dictionary form silently dropped every phrasing but one.
# Deliberately small and literal otherwise (see the module's "не
# переусложнять" instruction) rather than a general colour-name library —
# extend as real usage surfaces gaps.
_COLOR_STEMS_RU: dict[str, str] = {
    "красн": "#FF0000",
    "зелен": "#00FF00",
    "зелён": "#00FF00",
    "син": "#0000FF",
    "черн": "#000000",
    "чёрн": "#000000",
    "бел": "#FFFFFF",
    "желт": "#FFFF00",
    "жёлт": "#FFFF00",
    "оранжев": "#FFA500",
    "фиолетов": "#800080",
    "розов": "#FFC0CB",
    "сер": "#808080",
    "коричнев": "#A52A2A",
    "голуб": "#00BFFF",
    "бирюзов": "#40E0D0",
}

_ALIGNMENTS_RU: dict[str, str] = {
    "по левому краю": "left",
    "слева": "left",
    "влево": "left",
    "по правому краю": "right",
    "справа": "right",
    "вправо": "right",
    "по центру по горизонтали": "center_horizontal",
    "по горизонтали по центру": "center_horizontal",
    "по верхнему краю": "top",
    "наверх": "top",
    "сверху": "top",
    "по нижнему краю": "bottom",
    "вниз": "bottom",
    "снизу": "bottom",
    "по центру по вертикали": "center_vertical",
    "по вертикали по центру": "center_vertical",
    "по центру": "center_horizontal",
}


@dataclass(frozen=True)
class ParsedFigmaCommand:
    action: str
    params: dict[str, object]


@dataclass
class FigmaSessionState:
    """Tiny per-process voice-session context — this app is single-user/
    single-session (see core/state.py's StateManager for the equivalent
    pattern elsewhere), so a module-level singleton is enough; no need for
    per-conversation keys. modules/figma_control/dispatcher.py updates
    last_selected_layer after any action that creates or selects a layer,
    so a follow-up command like "сделай его красным" can resolve "его"
    without the user repeating the layer's name."""

    last_selected_layer: str | None = None


session_state = FigmaSessionState()


def _extract_color(text: str) -> str | None:
    hex_match = re.search(r"#[0-9a-fA-F]{6}\b", text)
    if hex_match:
        return hex_match.group(0)
    for stem, hex_value in _COLOR_STEMS_RU.items():
        if re.search(rf"\b{stem}\w*", text):
            return hex_value
    return None


def _extract_alignment(text: str) -> str | None:
    for phrase, alignment in _ALIGNMENTS_RU.items():
        if phrase in text:
            return alignment
    return None


def _resolve_layer_name(explicit: str | None) -> str | None:
    if explicit:
        return explicit.strip()
    return session_state.last_selected_layer


# Order matters: more specific patterns (with an explicit "слой <имя>")
# are checked before the vaguer "his/its" phrasing that falls back to
# session_state.last_selected_layer, same locality-of-check reasoning as
# core/voice/intent.py's interpret().
_CREATE_RECTANGLE = re.compile(r"прямоугольник(?:а|ом)?\s+(\d+)\s*(?:на|x|х|\*)\s*(\d+)")
_CREATE_FRAME = re.compile(
    r"фрейм(?:а|ом)?\s+(\d+)\s*(?:на|x|х|\*)\s*(\d+)(?:\s+(?:с именем|по имени|назови\w*)\s+(.+))?"
)
_CREATE_TEXT = re.compile(r"текст(?:а|ом)?\s+(?:с текстом|со словами|:)?\s*[«\"']?(.+?)[»\"']?$")
_SELECT_LAYER = re.compile(r"выдели\s+слой\s+(.+)")
_DELETE_LAYER = re.compile(r"удали\s+слой\s+(.+)")
_MOVE_LAYER = re.compile(
    r"(?:перемести|подвинь|передвинь)\s+слой\s+(.+?)\s+(?:на|в)\s+(\d+)\s*[, ]\s*(\d+)"
)
_RESIZE_LAYER = re.compile(
    r"измени\s+размер\s+слоя\s+(.+?)\s+на\s+(\d+)\s*(?:на|x|х|\*)\s*(\d+)"
)
_GROUP_SELECTION = re.compile(r"сгруппируй")
_ALIGN = re.compile(r"выровняй")
_EXPORT_SELECTION = re.compile(r"экспортируй\s+(?:выделение|слой)(?:\s+в\s+(\w+))?")
_UNDO = re.compile(r"^(?:отмени|отмена|верни назад)\b")
_REDO = re.compile(r"^(?:повтори|верни вперёд|верни вперед|redo)\b")
_CHANGE_COLOR_WITH_LAYER = re.compile(r"(?:покрась|перекрась)\s+слой\s+(.+?)\s+в\s+")
_CHANGE_COLOR_GENERIC = re.compile(r"(?:покрась|перекрась|сделай (?:его|её|ее))\b")


def _parse_with_patterns(text: str) -> ParsedFigmaCommand | None:
    normalized = text.strip().lower()
    if not normalized:
        return None

    match = _CREATE_RECTANGLE.search(normalized)
    if match:
        params: dict[str, object] = {"width": int(match.group(1)), "height": int(match.group(2))}
        color = _extract_color(normalized)
        if color:
            params["fill_color"] = color
        return ParsedFigmaCommand(action="create_rectangle", params=params)

    match = _CREATE_FRAME.search(normalized)
    if match:
        params = {"width": int(match.group(1)), "height": int(match.group(2))}
        if match.group(3):
            params["name"] = match.group(3).strip()
        return ParsedFigmaCommand(action="create_frame", params=params)

    match = _CREATE_TEXT.search(normalized)
    if match and match.group(1).strip():
        return ParsedFigmaCommand(action="create_text", params={"content": match.group(1).strip()})

    match = _MOVE_LAYER.search(normalized)
    if match:
        return ParsedFigmaCommand(
            action="move_layer",
            params={"layer_name": match.group(1).strip(), "x": int(match.group(2)), "y": int(match.group(3))},
        )

    match = _RESIZE_LAYER.search(normalized)
    if match:
        return ParsedFigmaCommand(
            action="resize_layer",
            params={
                "layer_name": match.group(1).strip(),
                "width": int(match.group(2)),
                "height": int(match.group(3)),
            },
        )

    match = _SELECT_LAYER.search(normalized)
    if match:
        layer_name = match.group(1).strip()
        return ParsedFigmaCommand(action="select_layer", params={"layer_name": layer_name})

    match = _DELETE_LAYER.search(normalized)
    if match:
        return ParsedFigmaCommand(action="delete_layer", params={"layer_name": match.group(1).strip()})

    if _CHANGE_COLOR_WITH_LAYER.search(normalized) or _CHANGE_COLOR_GENERIC.search(normalized):
        color = _extract_color(normalized)
        if color:
            explicit_match = _CHANGE_COLOR_WITH_LAYER.search(normalized)
            layer_name = _resolve_layer_name(explicit_match.group(1).strip() if explicit_match else None)
            if layer_name:
                return ParsedFigmaCommand(
                    action="change_color", params={"layer_name": layer_name, "color": color}
                )
            logger.info("Color-change command with no explicit or remembered layer name: %r", text)
            return None

    if _GROUP_SELECTION.search(normalized):
        return ParsedFigmaCommand(action="group_selection", params={})

    if _ALIGN.search(normalized):
        alignment = _extract_alignment(normalized)
        if alignment:
            return ParsedFigmaCommand(action="align", params={"alignment": alignment})
        return None

    match = _EXPORT_SELECTION.search(normalized)
    if match:
        return ParsedFigmaCommand(action="export_selection", params={"format": (match.group(1) or "png").upper()})

    if _UNDO.search(normalized):
        return ParsedFigmaCommand(action="undo", params={})

    if _REDO.search(normalized):
        return ParsedFigmaCommand(action="redo", params={})

    return None


def _build_ai_prompt(text: str) -> str:
    actions = ", ".join(sorted(KNOWN_ACTIONS))
    return (
        f"Пользователь дал голосовую команду для управления программой Figma: '{text}'. "
        f"Вот список доступных действий: {actions}. Определи, какое действие имел в виду пользователь, "
        "и извлеки его параметры (например layer_name, x, y, width, height, color, fill_color, name, "
        "content, alignment, format — только те, что применимы к выбранному действию и упомянуты в фразе). "
        "Значения alignment должны быть одним из: left, right, center_horizontal, center_vertical, top, bottom. "
        "Если команда не про управление Figma вообще или не подходит ни одно действие — верни null. "
        'Ответь ТОЛЬКО JSON-объектом без пояснений, строго в формате {"action": "<имя_или_null>", "params": {}}.'
    )


def _parse_ai_response(raw: str) -> ParsedFigmaCommand | None:
    match = _JSON_OBJECT_PATTERN.search(raw)
    if not match:
        logger.warning("Figma AI command parsing returned no JSON object")
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("Figma AI command parsing returned invalid JSON")
        return None

    action = parsed.get("action")
    if action not in KNOWN_ACTIONS:
        return None
    raw_params = parsed.get("params")
    params = raw_params if isinstance(raw_params, dict) else {}
    return ParsedFigmaCommand(action=action, params=params)


async def _parse_with_ai(text: str) -> ParsedFigmaCommand | None:
    prompt = _build_ai_prompt(text)
    for adapter in local_first_chain():
        try:
            raw = await adapter.send_prompt(prompt, fast_mode=True)
        except Exception as exc:
            logger.warning("Figma AI command parsing adapter '%s' failed: %s", adapter.name, exc, exc_info=exc)
            continue
        parsed = _parse_ai_response(raw)
        if parsed is not None:
            return parsed
    return None


async def parse_command(text: str) -> ParsedFigmaCommand | None:
    """Turn free voice text into a (action, params) pair the rest of the
    module can act on. Tries the fast literal patterns first (cheap, no AI
    round-trip); anything that doesn't match a known phrasing falls back to
    an AI-assisted structuring pass, same shape as
    modules/calendar/extraction.py and modules/ai_bridge/intent_classifier.py.
    Returns None when neither path could make sense of it."""
    parsed = _parse_with_patterns(text)
    if parsed is not None:
        return parsed
    return await _parse_with_ai(text)
