"""Entry point for Jarvis <-> Blender voice control.

process_blender_command(text) is the module's whole public surface for
actually running a command: parse -> check Blender is reachable -> send ->
speak the result. register_commands(dispatcher) wires exactly one command
("blender_command", a raw-text param) into the shared dispatcher — see this
function's own docstring below for why one generic command rather than one
per bpy action.
"""

from __future__ import annotations

import json
import re
from typing import Any

from core.ai_adapter_chain import free_api_first_chain
from core.dispatcher import CommandDispatcher
from core.logger import get_logger
from modules.blender_control import command_parser
from modules.blender_control.command_parser import NoActiveObjectError, ParsedCommand, blender_session
from modules.blender_control.ws_client import BlenderUnavailableError, blender_ws_client

logger = get_logger(__name__)

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)

_NOT_CONNECTED_MESSAGE = "Blender не подключён, запусти его с активным аддоном."

# Mirrors blender_addon/handlers.py's ACTIONS dispatch table (name -> short
# Russian description of what it does and which params it takes) — used only
# to build the AI-structuring prompt below when command_parser's rule-based
# patterns don't match, and to validate the AI's answer names a real action.
# Duplicated by necessity, not oversight: blender_addon runs inside
# Blender's own bundled Python, a separate process this backend can't import
# from — see handlers.py's own docstring.
_ACTIONS_HELP: dict[str, str] = {
    "create_primitive": "создать примитив: type (cube|sphere|cylinder|plane|cone), location [x,y,z], size",
    "delete_object": "удалить объект: name",
    "move_object": "переместить объект: name, location [x,y,z]",
    "rotate_object": "повернуть объект: name, rotation [x,y,z] в градусах",
    "scale_object": "изменить масштаб объекта: name, и либо scale [x,y,z], либо scale_factor (число)",
    "duplicate_object": "дублировать объект: name",
    "rename_object": "переименовать объект: old_name, new_name",
    "select_object": "выделить объект: name",
    "add_modifier": "добавить модификатор объекту: object_name, modifier_type (SUBSURF|BOOLEAN|ARRAY|MIRROR|SOLIDIFY|BEVEL)",
    "remove_modifier": "удалить модификатор с объекта: object_name, modifier_name",
    "apply_modifier": "применить (запечь) модификатор: object_name, modifier_name",
    "create_material": "создать материал: name, base_color [r,g,b], metallic, roughness",
    "assign_material": "назначить материал объекту: object_name, material_name",
    "switch_mode": "переключить режим Blender: mode (OBJECT|EDIT|SCULPT|POSE)",
    "switch_viewport_shading": "переключить отображение вьюпорта: shading (WIREFRAME|SOLID|MATERIAL|RENDERED)",
    "insert_keyframe": "вставить ключевой кадр: object_name, property (location|rotation|scale), frame",
    "set_current_frame": "перейти на кадр анимации: frame",
    "start_render": "запустить рендер сцены: output_path, format",
    "get_render_status": "узнать статус текущего рендера",
    "save_file": "сохранить файл сцены: path (необязательно)",
    "open_file": "открыть файл сцены: path",
    "undo": "отменить последнее действие в Blender",
    "redo": "повторить отменённое действие в Blender",
}


async def _structure_with_ai(text: str) -> ParsedCommand | None:
    """Last-resort structuring for a Blender-flavored phrase that matched
    none of command_parser's rule-based patterns — same "ask a model to
    return one JSON object naming a known action + params" approach
    modules/ai_bridge/intent_classifier.py uses for the whole app's command
    list, just scoped to Blender's own action vocabulary and only ever
    tried against the single fastest adapter (a structuring call like this
    isn't worth retrying across the whole provider chain if the first one
    fails — the caller already has a clear "couldn't understand" fallback
    message for that case)."""
    chain = free_api_first_chain()
    if not chain:
        return None
    adapter = chain[0]

    action_list = "; ".join(f"{name} — {help_text}" for name, help_text in _ACTIONS_HELP.items())
    prompt = (
        f"Пользователь дал голосовую команду для управления 3D-редактором Blender: '{text}'. "
        f"Вот список доступных действий: {action_list}. Определи, какое действие имел в виду "
        "пользователь, и извлеки параметры из фразы под именами, указанными выше. Ответь ТОЛЬКО "
        'JSON-объектом без пояснений, строго в формате {"action": "<имя_действия_или_null>", '
        '"params": {}}. Если ни одно действие не подходит, "action" должен быть null.'
    )

    try:
        raw = await adapter.send_prompt(prompt, fast_mode=True)
    except Exception:
        logger.exception("AI structuring of a Blender command failed")
        return None

    match = _JSON_OBJECT_PATTERN.search(raw)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None

    action = parsed.get("action")
    if action not in _ACTIONS_HELP:
        return None
    params = parsed.get("params")
    if not isinstance(params, dict):
        params = {}
    return ParsedCommand(action, params)


def _update_session(data: dict[str, Any]) -> None:
    name = data.get("new_name") or data.get("name")
    if name:
        blender_session.set_last_active_object(name)


def _success_message(action: str, params: dict[str, Any], data: dict[str, Any]) -> str:
    if action == "create_primitive":
        return f"Готово, создан объект {data.get('name', '')}".strip()
    if action == "delete_object":
        return f"Объект {params.get('name', '')} удалён".strip()
    if action == "move_object":
        return f"Объект {params.get('name', '')} перемещён".strip()
    if action == "rotate_object":
        return f"Объект {params.get('name', '')} повёрнут".strip()
    if action == "scale_object":
        return f"Размер объекта {params.get('name', '')} изменён".strip()
    if action == "duplicate_object":
        return f"Создана копия: {data.get('name', '')}".strip()
    if action == "rename_object":
        return f"Объект переименован в {data.get('new_name', '')}".strip()
    if action == "select_object":
        return f"Выделен объект {params.get('name', '')}".strip()
    if action == "add_modifier":
        return f"Модификатор {params.get('modifier_type', '')} добавлен".strip()
    if action == "remove_modifier":
        return "Модификатор удалён"
    if action == "apply_modifier":
        return "Модификатор применён"
    if action == "create_material":
        return f"Материал {data.get('name', '')} создан".strip()
    if action == "assign_material":
        return "Материал назначен"
    if action == "switch_mode":
        return "Режим переключён"
    if action == "switch_viewport_shading":
        return "Отображение вьюпорта изменено"
    if action == "insert_keyframe":
        return "Ключевой кадр добавлен"
    if action == "set_current_frame":
        return f"Текущий кадр: {data.get('frame', '')}".strip()
    if action == "start_render":
        return "Рендер запущен"
    if action == "get_render_status":
        state = data.get("state")
        return {
            "running": "Рендер ещё выполняется",
            "done": "Рендер завершён",
            "failed": f"Рендер завершился с ошибкой: {data.get('error', '')}",
            "cancelled": "Рендер отменён",
            "idle": "Рендер ещё не запускался",
        }.get(state, "Не удалось определить статус рендера")
    if action == "save_file":
        return "Файл сохранён"
    if action == "open_file":
        return "Файл открыт"
    if action == "undo":
        return "Действие отменено"
    if action == "redo":
        return "Действие повторено"
    return "Готово."


async def process_blender_command(text: str) -> str:
    """1. parse `text` (rule-based, then AI structuring as a fallback);
    2. bail out early with a clear message if Blender/the addon isn't
    reachable; 3. send the command; 4. return a short Russian sentence for
    TTS describing what happened."""
    try:
        parsed = command_parser.parse(text, blender_session)
    except NoActiveObjectError:
        return "Не понимаю, к какому объекту это относится — сначала назови его или создай в Blender."

    if parsed is None:
        parsed = await _structure_with_ai(text)
    if parsed is None:
        return "Не удалось распознать команду для Blender."

    if not await blender_ws_client.is_blender_connected():
        return _NOT_CONNECTED_MESSAGE

    try:
        response = await blender_ws_client.send_command(parsed.action, parsed.params)
    except BlenderUnavailableError as exc:
        logger.warning("Blender command '%s' failed: %s", parsed.action, exc)
        return _NOT_CONNECTED_MESSAGE

    data = response.get("data") or {}
    if response.get("status") != "success":
        message = response.get("message") or "неизвестная ошибка"
        logger.warning("Blender rejected command '%s': %s", parsed.action, message)
        return f"Ошибка в Blender: {message}"

    _update_session(data)
    return _success_message(parsed.action, parsed.params, data)


async def _handle_blender_command(params: dict[str, Any]) -> dict[str, Any]:
    text = params.get("text")
    if not text:
        raise ValueError("Missing required parameter 'text'")
    message = await process_blender_command(text)
    return {"message": message}


def register_commands(dispatcher: CommandDispatcher) -> None:
    # A single generic command (rather than one dispatcher entry per bpy
    # action) so the existing global AI intent_classifier — which matches
    # free text against core.dispatcher's whole command list by description
    # (see modules/ai_bridge/intent_classifier.py) — only needs one
    # Blender-flavored candidate to route any Blender-related utterance to.
    # From there, command_parser.py's rule-based patterns (and, failing
    # those, this module's own narrower AI-structuring step above) turn the
    # raw text into a specific bpy action — see process_blender_command.
    dispatcher.register(
        "blender_command",
        _handle_blender_command,
        dangerous=False,
        description=(
            "Управление 3D-редактором Blender голосом: создание/удаление/перемещение/поворот/"
            "масштабирование объектов (куб, сфера, цилиндр, плоскость, конус), модификаторы "
            "(subdivision, boolean, array, mirror и другие), материалы, переключение режима "
            "(объектный, редактирования, скульптинга, позирования) и отображения вьюпорта, "
            "ключевые кадры анимации, запуск рендера, сохранение и открытие файла сцены, отмена "
            "и повтор действия. Использовать при любом упоминании Blender или 3D-моделирования "
            "(text — полная исходная фраза пользователя)."
        ),
    )
