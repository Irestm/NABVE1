"""Rule-based Russian voice -> Blender action parser.

Mirrors the shape of core/voice/intent.py's rule-based patterns (checked
first, cheap, no AI round-trip) but stays local to this module rather than
living in that shared file: unlike intent.py's patterns, these don't need to
plug into the global dispatcher-command list, since modules/blender_control
registers exactly one dispatcher command ("blender_command", a raw text
param — see dispatcher.py) that the global AI intent_classifier routes any
Blender-flavored utterance to; parsing that raw text into a specific bpy
action + params is this module's own job from there.

Deliberately Russian-only (this user's primary voice language for this
project) and covers the commands named in the spec, not full NLU — anything
that doesn't match one of these patterns falls through to dispatcher.py's
own AI-structuring step, same as every other free-text command elsewhere in
Jarvis.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

_NUMBER_PATTERN = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


class NoActiveObjectError(Exception):
    """Raised when a command refers to an object only implicitly (a pronoun
    like "его", or a bare primitive-type word like "куб" instead of a real
    Blender object name) and there's no last_active_object to resolve it
    against yet."""


@dataclass(frozen=True)
class ParsedCommand:
    action: str
    params: dict[str, object]


class BlenderSession:
    """Per-process "what did we just do in Blender" context, so a follow-up
    command like "сделай его больше" doesn't require re-naming the object.
    Same shape as core/state.py's StateManager (a small lock-guarded mailbox)
    — this assistant is single-user/single-session, so a module-level
    singleton is enough; no need for per-conversation or per-user scoping."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_active_object: str | None = None

    @property
    def last_active_object(self) -> str | None:
        with self._lock:
            return self._last_active_object

    def set_last_active_object(self, name: str | None) -> None:
        with self._lock:
            self._last_active_object = name


blender_session = BlenderSession()

# Blender's own default names for bpy.ops.mesh.primitive_*_add() are English
# ("Cube", "Sphere", ...), not the Russian word the user actually said, so a
# bare Russian type word ("куб") can never literally match a real object
# name. Voice UX for these words also almost always means "the one I just
# made/last touched" rather than a literal identifier anyway, so they
# resolve through last_active_object exactly like a pronoun does — see
# _resolve_object_ref below.
_PRIMITIVE_TYPES: dict[str, str] = {
    "куб": "cube", "кубик": "cube",
    "сферу": "sphere", "сфера": "sphere", "шар": "sphere",
    "цилиндр": "cylinder",
    "плоскость": "plane",
    "конус": "cone",
}

# Word stems (not full forms) for the same "does this token even refer to a
# real object name" check as _PRIMITIVE_TYPES above, tolerant of Russian
# noun declension: a governing preposition changes the case ending ("к
# кубу", "у куба", "с кубом", ...), so matching the bare dictionary form
# alone would miss every prepositional phrase. Checked via startswith, not
# equality — see _resolve_object_ref.
_PRIMITIVE_STEMS: tuple[str, ...] = ("куб", "сфер", "шар", "цилиндр", "плоскост", "конус")

_PRONOUNS = {"его", "её", "это", "этот", "текущий", "объект", "текущий объект"}

_MODIFIER_TYPES: dict[str, str] = {
    "subdivision": "SUBSURF", "сабдив": "SUBSURF", "сглаживание": "SUBSURF",
    "boolean": "BOOLEAN", "булеан": "BOOLEAN", "буль": "BOOLEAN",
    "array": "ARRAY", "массив": "ARRAY",
    "mirror": "MIRROR", "зеркало": "MIRROR",
    "solidify": "SOLIDIFY", "солидифай": "SOLIDIFY", "утолщение": "SOLIDIFY",
    "bevel": "BEVEL", "фаска": "BEVEL",
}

_MODE_TYPES: dict[str, str] = {
    "редактирования": "EDIT", "редактирование": "EDIT",
    "объектный": "OBJECT", "объекта": "OBJECT",
    "скульптинга": "SCULPT", "скульптинг": "SCULPT",
    "позирования": "POSE", "позы": "POSE",
}

_SHADING_TYPES: dict[str, str] = {
    "каркасный": "WIREFRAME",
    "сплошной": "SOLID",
    "материальный": "MATERIAL", "материалы": "MATERIAL",
    "рендер": "RENDERED",
}


def _numbers(text: str) -> list[float]:
    return [float(match.replace(",", ".")) for match in _NUMBER_PATTERN.findall(text)]


def _resolve_object_ref(token: str, session: BlenderSession) -> str:
    stripped = token.strip()
    normalized = stripped.lower()
    is_implicit_ref = normalized in _PRONOUNS or any(normalized.startswith(stem) for stem in _PRIMITIVE_STEMS)
    if is_implicit_ref:
        last = session.last_active_object
        if last is None:
            raise NoActiveObjectError(f"No last active object to resolve '{token}' against")
        return last
    return stripped


def _vec3_from_numbers(numbers: list[float]) -> list[float]:
    if len(numbers) >= 3:
        return numbers[:3]
    if len(numbers) == 1:
        # A single bare number ("поверни куб на 90") is the common
        # shorthand for "rotate/move around the vertical (Z) axis" in
        # everyday Blender voice phrasing.
        return [0.0, 0.0, numbers[0]]
    raise ValueError(f"Expected 1 or 3 numbers, got {len(numbers)}")


def parse(text: str, session: BlenderSession = blender_session) -> ParsedCommand | None:
    """Returns the matched (action, params) for `text`, or None if nothing
    here matches — the caller (dispatcher.py) falls back to AI structuring
    in that case. Raises NoActiveObjectError if a pattern matched but its
    implicit object reference ("его"/"куб") can't be resolved yet.

    Matching is case-insensitive (re.IGNORECASE below), but `text`'s
    original casing is otherwise preserved throughout — captured object/
    material/file names are real Blender identifiers and paths, which are
    case-sensitive ("MyCube" != "mycube"). A keyword-only capture (a
    primitive/modifier/mode/shading word looked up in one of the dicts
    above) is explicitly .lower()'d right before that one lookup, since
    those dicts only ever hand back a fixed constant, never the captured
    text itself."""
    original = text.strip().rstrip(".!")
    if not original:
        return None
    normalized = original.lower()

    match = re.match(
        r"^(?:создай|добавь|сделай)\s+(куб|кубик|сферу|сфера|шар|цилиндр|плоскость|конус)"
        r"(?:\s+размером?\s+([\d.,]+))?$",
        original,
        re.IGNORECASE,
    )
    if match:
        kind = _PRIMITIVE_TYPES[match.group(1).lower()]
        params: dict[str, object] = {"type": kind}
        if match.group(2):
            params["size"] = float(match.group(2).replace(",", "."))
        return ParsedCommand("create_primitive", params)

    match = re.match(r"^удали\s+модификатор\s+(\S+)\s+(?:у|с|на)\s+(.+)$", original, re.IGNORECASE)
    if match:
        modifier = _MODIFIER_TYPES.get(match.group(1).lower(), match.group(1).upper())
        object_ref = _resolve_object_ref(match.group(2), session)
        return ParsedCommand("remove_modifier", {"object_name": object_ref, "modifier_name": modifier})

    match = re.match(r"^запеки\s+модификатор\s+(\S+)(?:\s+(?:у|на)\s+(.+))?$", original, re.IGNORECASE)
    if match:
        modifier = _MODIFIER_TYPES.get(match.group(1).lower(), match.group(1).upper())
        object_ref = _resolve_object_ref(match.group(2) or "его", session)
        return ParsedCommand("apply_modifier", {"object_name": object_ref, "modifier_name": modifier})

    match = re.match(r"^(?:примени|добавь)\s+модификатор\s+(\S+)\s+(?:к|на)\s+(.+)$", original, re.IGNORECASE)
    if match:
        modifier = _MODIFIER_TYPES.get(match.group(1).lower(), match.group(1).upper())
        object_ref = _resolve_object_ref(match.group(2), session)
        return ParsedCommand("add_modifier", {"object_name": object_ref, "modifier_type": modifier, "settings": {}})

    match = re.match(r"^удали\s+(.+)$", original, re.IGNORECASE)
    if match:
        object_ref = _resolve_object_ref(match.group(1), session)
        return ParsedCommand("delete_object", {"name": object_ref})

    match = re.match(r"^(?:передвинь|перемести)\s+(.+?)\s+на\s+(.+)$", original, re.IGNORECASE)
    if match:
        object_ref = _resolve_object_ref(match.group(1), session)
        location = _vec3_from_numbers(_numbers(match.group(2)))
        return ParsedCommand("move_object", {"name": object_ref, "location": location})

    match = re.match(r"^поверни\s+(.+?)\s+на\s+(.+)$", original, re.IGNORECASE)
    if match:
        object_ref = _resolve_object_ref(match.group(1), session)
        rotation = _vec3_from_numbers(_numbers(match.group(2)))
        return ParsedCommand("rotate_object", {"name": object_ref, "rotation": rotation})

    match = re.match(r"^сделай\s+(.+?)\s+(больше|меньше)$", original, re.IGNORECASE)
    if match:
        object_ref = _resolve_object_ref(match.group(1), session)
        factor = 1.5 if match.group(2).lower() == "больше" else (1 / 1.5)
        return ParsedCommand("scale_object", {"name": object_ref, "scale_factor": factor})

    match = re.match(r"^(?:масштабируй|измени размер)\s+(.+?)\s+(?:в|на)\s+([\d.,]+)(?:\s*раза?)?$", original, re.IGNORECASE)
    if match:
        object_ref = _resolve_object_ref(match.group(1), session)
        factor = float(match.group(2).replace(",", "."))
        return ParsedCommand("scale_object", {"name": object_ref, "scale_factor": factor})

    match = re.match(r"^(?:дублируй|скопируй)\s+(.+)$", original, re.IGNORECASE)
    if match:
        object_ref = _resolve_object_ref(match.group(1), session)
        return ParsedCommand("duplicate_object", {"name": object_ref})

    match = re.match(r"^переименуй\s+(.+?)\s+в\s+(.+)$", original, re.IGNORECASE)
    if match:
        object_ref = _resolve_object_ref(match.group(1), session)
        return ParsedCommand("rename_object", {"old_name": object_ref, "new_name": match.group(2).strip()})

    match = re.match(r"^(?:выдели|выбери)\s+(.+)$", original, re.IGNORECASE)
    if match:
        object_ref = _resolve_object_ref(match.group(1), session)
        return ParsedCommand("select_object", {"name": object_ref})

    match = re.match(r"^создай\s+материал\s+(.+)$", original, re.IGNORECASE)
    if match:
        return ParsedCommand("create_material", {"name": match.group(1).strip()})

    match = re.match(r"^(?:назначь|примени)\s+материал\s+(.+?)\s+(?:на|к)\s+(.+)$", original, re.IGNORECASE)
    if match:
        object_ref = _resolve_object_ref(match.group(2), session)
        return ParsedCommand("assign_material", {"object_name": object_ref, "material_name": match.group(1).strip()})

    match = re.match(r"^переключись?\s+в\s+режим\s+(\S+)$", original, re.IGNORECASE)
    if match and match.group(1).lower() in _MODE_TYPES:
        return ParsedCommand("switch_mode", {"mode": _MODE_TYPES[match.group(1).lower()]})

    match = re.match(r"^переключи\s+вьюпорт\s+в\s+(\S+)(?:\s+режим)?$", original, re.IGNORECASE)
    if match and match.group(1).lower() in _SHADING_TYPES:
        return ParsedCommand("switch_viewport_shading", {"shading": _SHADING_TYPES[match.group(1).lower()]})

    match = re.match(
        r"^(?:поставь|вставь)\s+ключевой\s+кадр(?:\s+для\s+(.+?))?(?:\s+на\s+кадре\s+(\d+))?$", original, re.IGNORECASE
    )
    if match:
        object_ref = _resolve_object_ref(match.group(1) or "его", session)
        params = {"object_name": object_ref, "property": "location"}
        if match.group(2):
            params["frame"] = int(match.group(2))
        return ParsedCommand("insert_keyframe", params)

    match = re.match(r"^перейди\s+на\s+кадр\s+(\d+)$", original, re.IGNORECASE)
    if match:
        return ParsedCommand("set_current_frame", {"frame": int(match.group(1))})

    if normalized == "запусти рендер":
        return ParsedCommand("start_render", {})

    if normalized in ("статус рендера", "какой статус рендера"):
        return ParsedCommand("get_render_status", {})

    match = re.match(r"^сохрани\s+файл(?:\s+как\s+(.+))?$", original, re.IGNORECASE)
    if match:
        params = {}
        if match.group(1):
            params["path"] = match.group(1).strip()
        return ParsedCommand("save_file", params)

    match = re.match(r"^открой\s+файл\s+(.+)$", original, re.IGNORECASE)
    if match:
        return ParsedCommand("open_file", {"path": match.group(1).strip()})

    if normalized in ("отмени", "отмена", "отмени действие"):
        return ParsedCommand("undo", {})

    if normalized in ("верни", "повтори", "верни действие"):
        return ParsedCommand("redo", {})

    return None
