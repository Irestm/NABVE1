"""bpy action handlers for the Jarvis Blender remote-control addon.

Every function here has the same signature — (params: dict) -> dict — and is
only ever called from server.py's bpy.app.timers callback, i.e. already on
Blender's main thread. None of these functions do their own threading; that
plumbing lives entirely in server.py so this module can stay plain bpy code.

ACTIONS is the dispatch table server.py looks actions up in by name (mirrors
the {"action": str, "params": dict} wire protocol). Keep the action names
here in sync with modules/blender_control/command_parser.py and
modules/blender_control/dispatcher.py on the Jarvis backend side — the two
sides live in separate Python processes (Blender's bundled interpreter vs.
the backend venv) and can't share a literal import, so the action-name
vocabulary is duplicated by necessity, not oversight.
"""

from __future__ import annotations

import os
from typing import Any, Callable

import bpy

RENDER_STATUS_IDLE = "idle"
RENDER_STATUS_RUNNING = "running"
RENDER_STATUS_DONE = "done"
RENDER_STATUS_FAILED = "failed"
RENDER_STATUS_CANCELLED = "cancelled"

# Updated by the render handlers registered in _ensure_render_handlers()
# below and read by get_render_status() — this is the async-render status
# cell start_render() hands back a "started" reply for immediately, rather
# than blocking the whole main-thread timer callback for however long the
# render actually takes (which would freeze Blender's UI and every other
# pending command for the same duration).
_render_status: dict[str, Any] = {"state": RENDER_STATUS_IDLE, "output_path": None, "error": None}

_PRIMITIVE_ADD_OPS: dict[str, Callable[..., Any]] = {
    "cube": bpy.ops.mesh.primitive_cube_add,
    "sphere": bpy.ops.mesh.primitive_uv_sphere_add,
    "cylinder": bpy.ops.mesh.primitive_cylinder_add,
    "plane": bpy.ops.mesh.primitive_plane_add,
    "cone": bpy.ops.mesh.primitive_cone_add,
}

_MODE_VALUES = {"OBJECT", "EDIT", "SCULPT", "POSE", "VERTEX_PAINT", "WEIGHT_PAINT", "TEXTURE_PAINT"}
_SHADING_VALUES = {"WIREFRAME", "SOLID", "MATERIAL", "RENDERED"}


class BlenderCommandError(Exception):
    """Raised by a handler for a caller mistake (unknown object/type/mode,
    missing required param, ...). server.py catches this (and any other
    exception) and turns it into a {"status": "error"} reply — handlers
    themselves never need to touch the wire format."""


def _require(params: dict[str, Any], key: str) -> Any:
    value = params.get(key)
    if value in (None, ""):
        raise BlenderCommandError(f"Missing required parameter '{key}'")
    return value


def _get_object(name: str) -> bpy.types.Object:
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise BlenderCommandError(f"No object named '{name}'")
    return obj


def _vec3(value: Any, *, fallback: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    if value is None:
        return fallback
    if len(value) != 3:
        raise BlenderCommandError("Expected a 3-component [x, y, z] value")
    return (float(value[0]), float(value[1]), float(value[2]))


# --- Objects -----------------------------------------------------------

def create_primitive(params: dict[str, Any]) -> dict[str, Any]:
    kind = _require(params, "type").lower()
    op = _PRIMITIVE_ADD_OPS.get(kind)
    if op is None:
        raise BlenderCommandError(f"Unknown primitive type '{kind}', expected one of {sorted(_PRIMITIVE_ADD_OPS)}")

    location = _vec3(params.get("location"))
    size = params.get("size")
    kwargs: dict[str, Any] = {"location": location}
    # bpy's primitive_*_add operators don't share a single "size" kwarg name
    # (cube/plane take size=, sphere/cylinder/cone take radius=), so a
    # generic voice-level "size" param maps to whichever the target
    # primitive actually accepts.
    if size is not None:
        if kind in ("cube", "plane"):
            kwargs["size"] = float(size)
        else:
            kwargs["radius"] = float(size)

    op(**kwargs)
    obj = bpy.context.active_object
    return {"name": obj.name, "type": kind, "location": list(obj.location)}


def delete_object(params: dict[str, Any]) -> dict[str, Any]:
    name = _require(params, "name")
    obj = _get_object(name)
    bpy.data.objects.remove(obj, do_unlink=True)
    return {"name": name}


def move_object(params: dict[str, Any]) -> dict[str, Any]:
    name = _require(params, "name")
    obj = _get_object(name)
    obj.location = _vec3(params.get("location"), fallback=tuple(obj.location))
    return {"name": name, "location": list(obj.location)}


def rotate_object(params: dict[str, Any]) -> dict[str, Any]:
    import math

    name = _require(params, "name")
    obj = _get_object(name)
    degrees = _vec3(params.get("rotation"), fallback=tuple(math.degrees(a) for a in obj.rotation_euler))
    obj.rotation_euler = tuple(math.radians(d) for d in degrees)
    return {"name": name, "rotation": list(degrees)}


def scale_object(params: dict[str, Any]) -> dict[str, Any]:
    name = _require(params, "name")
    obj = _get_object(name)
    # Absolute {"scale": [x, y, z]} takes priority; {"scale_factor": f} is a
    # relative multiply on top of the current scale — the shape command_parser
    # needs for "сделай его больше"/"сделай его меньше" without the object's
    # current scale being known on the voice side.
    if params.get("scale") is not None:
        obj.scale = _vec3(params["scale"])
    elif params.get("scale_factor") is not None:
        factor = float(params["scale_factor"])
        obj.scale = tuple(component * factor for component in obj.scale)
    else:
        raise BlenderCommandError("Expected either 'scale' or 'scale_factor'")
    return {"name": name, "scale": list(obj.scale)}


def duplicate_object(params: dict[str, Any]) -> dict[str, Any]:
    name = _require(params, "name")
    obj = _get_object(name)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.duplicate()
    new_obj = bpy.context.active_object
    return {"name": new_obj.name, "source": name}


def rename_object(params: dict[str, Any]) -> dict[str, Any]:
    old_name = _require(params, "old_name")
    new_name = _require(params, "new_name")
    obj = _get_object(old_name)
    obj.name = new_name
    return {"old_name": old_name, "new_name": obj.name}


def select_object(params: dict[str, Any]) -> dict[str, Any]:
    name = _require(params, "name")
    obj = _get_object(name)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return {"name": name}


# --- Modifiers -----------------------------------------------------------

def add_modifier(params: dict[str, Any]) -> dict[str, Any]:
    object_name = _require(params, "object_name")
    modifier_type = _require(params, "modifier_type").upper()
    obj = _get_object(object_name)
    try:
        modifier = obj.modifiers.new(name=modifier_type.title(), type=modifier_type)
    except Exception as exc:
        raise BlenderCommandError(f"Could not add modifier of type '{modifier_type}': {exc}") from exc

    for key, value in (params.get("settings") or {}).items():
        if not hasattr(modifier, key):
            raise BlenderCommandError(f"Modifier '{modifier_type}' has no setting '{key}'")
        setattr(modifier, key, value)

    return {"object_name": object_name, "modifier_name": modifier.name, "modifier_type": modifier_type}


def remove_modifier(params: dict[str, Any]) -> dict[str, Any]:
    object_name = _require(params, "object_name")
    modifier_name = _require(params, "modifier_name")
    obj = _get_object(object_name)
    modifier = obj.modifiers.get(modifier_name)
    if modifier is None:
        raise BlenderCommandError(f"Object '{object_name}' has no modifier named '{modifier_name}'")
    obj.modifiers.remove(modifier)
    return {"object_name": object_name, "modifier_name": modifier_name}


def apply_modifier(params: dict[str, Any]) -> dict[str, Any]:
    object_name = _require(params, "object_name")
    modifier_name = _require(params, "modifier_name")
    obj = _get_object(object_name)
    if obj.modifiers.get(modifier_name) is None:
        raise BlenderCommandError(f"Object '{object_name}' has no modifier named '{modifier_name}'")

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    result = bpy.ops.object.modifier_apply(modifier=modifier_name)
    if "FINISHED" not in result:
        raise BlenderCommandError(f"Failed to apply modifier '{modifier_name}' on '{object_name}'")
    return {"object_name": object_name, "modifier_name": modifier_name}


# --- Materials -------------------------------------------------------------

def create_material(params: dict[str, Any]) -> dict[str, Any]:
    name = _require(params, "name")
    material = bpy.data.materials.new(name=name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")

    base_color = params.get("base_color")
    if base_color is not None:
        color = tuple(base_color) + (1.0,) if len(base_color) == 3 else tuple(base_color)
        material.diffuse_color = color
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = color

    metallic = params.get("metallic")
    if metallic is not None:
        material.metallic = float(metallic)
        if bsdf is not None:
            bsdf.inputs["Metallic"].default_value = float(metallic)

    roughness = params.get("roughness")
    if roughness is not None:
        material.roughness = float(roughness)
        if bsdf is not None:
            bsdf.inputs["Roughness"].default_value = float(roughness)

    return {"name": material.name}


def assign_material(params: dict[str, Any]) -> dict[str, Any]:
    object_name = _require(params, "object_name")
    material_name = _require(params, "material_name")
    obj = _get_object(object_name)
    material = bpy.data.materials.get(material_name)
    if material is None:
        raise BlenderCommandError(f"No material named '{material_name}'")
    if obj.data is None or not hasattr(obj.data, "materials"):
        raise BlenderCommandError(f"Object '{object_name}' cannot hold materials")

    if len(obj.data.materials) == 0:
        obj.data.materials.append(material)
    else:
        obj.data.materials[0] = material
    return {"object_name": object_name, "material_name": material_name}


# --- Modes & viewport --------------------------------------------------

def switch_mode(params: dict[str, Any]) -> dict[str, Any]:
    mode = _require(params, "mode").upper()
    if mode not in _MODE_VALUES:
        raise BlenderCommandError(f"Unknown mode '{mode}', expected one of {sorted(_MODE_VALUES)}")
    if bpy.context.active_object is None:
        raise BlenderCommandError("No active object to switch mode on")
    bpy.ops.object.mode_set(mode=mode)
    return {"mode": mode}


def switch_viewport_shading(params: dict[str, Any]) -> dict[str, Any]:
    shading = _require(params, "shading").upper()
    if shading not in _SHADING_VALUES:
        raise BlenderCommandError(f"Unknown shading '{shading}', expected one of {sorted(_SHADING_VALUES)}")

    found = False
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.shading.type = shading
                    found = True
    if not found:
        raise BlenderCommandError("No 3D viewport area found to change shading on")
    return {"shading": shading}


# --- Animation -----------------------------------------------------------

_KEYFRAME_PROPERTIES = {"location", "rotation", "scale"}
_KEYFRAME_DATA_PATH = {"location": "location", "rotation": "rotation_euler", "scale": "scale"}


def insert_keyframe(params: dict[str, Any]) -> dict[str, Any]:
    object_name = _require(params, "object_name")
    prop = _require(params, "property").lower()
    if prop not in _KEYFRAME_PROPERTIES:
        raise BlenderCommandError(f"Unknown property '{prop}', expected one of {sorted(_KEYFRAME_PROPERTIES)}")
    obj = _get_object(object_name)

    frame = params.get("frame")
    if frame is not None:
        bpy.context.scene.frame_set(int(frame))

    obj.keyframe_insert(data_path=_KEYFRAME_DATA_PATH[prop])
    return {"object_name": object_name, "property": prop, "frame": bpy.context.scene.frame_current}


def set_current_frame(params: dict[str, Any]) -> dict[str, Any]:
    frame = _require(params, "frame")
    bpy.context.scene.frame_set(int(frame))
    return {"frame": bpy.context.scene.frame_current}


# --- Render ----------------------------------------------------------------

def _ensure_render_handlers() -> None:
    if _on_render_complete not in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.append(_on_render_complete)
    if _on_render_cancel not in bpy.app.handlers.render_cancel:
        bpy.app.handlers.render_cancel.append(_on_render_cancel)


def _on_render_complete(_scene: Any) -> None:
    _render_status["state"] = RENDER_STATUS_DONE
    _render_status["error"] = None


def _on_render_cancel(_scene: Any) -> None:
    _render_status["state"] = RENDER_STATUS_CANCELLED


def start_render(params: dict[str, Any]) -> dict[str, Any]:
    """Kicks the render off and returns immediately with 'started' rather
    than the finished render — bpy.ops.render.render() is synchronous and
    can run for minutes to hours, and blocking Blender's main thread (which
    is where this handler always runs — see server.py) for that whole
    duration would freeze the UI and every other queued command along with
    it. Progress is instead tracked via the render_complete/render_cancel
    handlers above and read back through get_render_status()."""
    if _render_status["state"] == RENDER_STATUS_RUNNING:
        raise BlenderCommandError("A render is already in progress")

    _ensure_render_handlers()

    output_path = params.get("output_path")
    if output_path:
        bpy.context.scene.render.filepath = output_path
    fmt = params.get("format")
    if fmt:
        bpy.context.scene.render.image_settings.file_format = fmt.upper()

    _render_status["state"] = RENDER_STATUS_RUNNING
    _render_status["output_path"] = bpy.context.scene.render.filepath
    _render_status["error"] = None

    try:
        # write_still=True so a still-image render actually lands on disk;
        # animation renders (params.get("animation")) don't need it.
        bpy.ops.render.render(
            "INVOKE_DEFAULT", write_still=not params.get("animation", False), animation=bool(params.get("animation", False))
        )
    except RuntimeError as exc:
        _render_status["state"] = RENDER_STATUS_FAILED
        _render_status["error"] = str(exc)
        raise BlenderCommandError(f"Could not start render: {exc}") from exc

    return {"state": RENDER_STATUS_RUNNING, "output_path": _render_status["output_path"]}


def get_render_status(_params: dict[str, Any]) -> dict[str, Any]:
    return dict(_render_status)


# --- Scene -------------------------------------------------------------

def save_file(params: dict[str, Any]) -> dict[str, Any]:
    path = params.get("path")
    if path:
        bpy.ops.wm.save_as_mainfile(filepath=path)
    else:
        bpy.ops.wm.save_mainfile()
    return {"path": path or bpy.data.filepath}


def open_file(params: dict[str, Any]) -> dict[str, Any]:
    path = _require(params, "path")
    if not os.path.isfile(path):
        raise BlenderCommandError(f"No .blend file at '{path}'")
    bpy.ops.wm.open_mainfile(filepath=path)
    return {"path": path}


def undo(_params: dict[str, Any]) -> dict[str, Any]:
    bpy.ops.ed.undo()
    return {}


def redo(_params: dict[str, Any]) -> dict[str, Any]:
    bpy.ops.ed.redo()
    return {}


ACTIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "create_primitive": create_primitive,
    "delete_object": delete_object,
    "move_object": move_object,
    "rotate_object": rotate_object,
    "scale_object": scale_object,
    "duplicate_object": duplicate_object,
    "rename_object": rename_object,
    "select_object": select_object,
    "add_modifier": add_modifier,
    "remove_modifier": remove_modifier,
    "apply_modifier": apply_modifier,
    "create_material": create_material,
    "assign_material": assign_material,
    "switch_mode": switch_mode,
    "switch_viewport_shading": switch_viewport_shading,
    "insert_keyframe": insert_keyframe,
    "set_current_frame": set_current_frame,
    "start_render": start_render,
    "get_render_status": get_render_status,
    "save_file": save_file,
    "open_file": open_file,
    "undo": undo,
    "redo": redo,
}


def dispatch(action: str, params: dict[str, Any]) -> dict[str, Any]:
    handler = ACTIONS.get(action)
    if handler is None:
        raise BlenderCommandError(f"Unknown action '{action}'")
    return handler(params or {})
