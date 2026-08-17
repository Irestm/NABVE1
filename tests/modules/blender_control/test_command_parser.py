from __future__ import annotations

import pytest

from modules.blender_control.command_parser import (
    BlenderSession,
    NoActiveObjectError,
    ParsedCommand,
    parse,
)


@pytest.fixture()
def session() -> BlenderSession:
    return BlenderSession()


def test_unmatched_text_returns_none(session: BlenderSession) -> None:
    assert parse("расскажи мне анекдот", session) is None


def test_empty_text_returns_none(session: BlenderSession) -> None:
    assert parse("   ", session) is None


def test_create_primitive_without_size(session: BlenderSession) -> None:
    result = parse("создай куб", session)
    assert result == ParsedCommand("create_primitive", {"type": "cube"})


def test_create_primitive_with_size(session: BlenderSession) -> None:
    result = parse("сделай сферу размером 2.5", session)
    assert result == ParsedCommand("create_primitive", {"type": "sphere", "size": 2.5})


def test_create_primitive_with_comma_decimal_size(session: BlenderSession) -> None:
    result = parse("добавь цилиндр размером 1,5", session)
    assert result == ParsedCommand("create_primitive", {"type": "cylinder", "size": 1.5})


def test_delete_object_by_explicit_name(session: BlenderSession) -> None:
    result = parse("удали MyCube", session)
    assert result == ParsedCommand("delete_object", {"name": "MyCube"})


def test_delete_object_by_pronoun_resolves_last_active_object(session: BlenderSession) -> None:
    session.set_last_active_object("Cube")
    result = parse("удали его", session)
    assert result == ParsedCommand("delete_object", {"name": "Cube"})


def test_delete_object_by_pronoun_without_last_active_raises(session: BlenderSession) -> None:
    with pytest.raises(NoActiveObjectError):
        parse("удали его", session)


def test_delete_object_by_primitive_word_resolves_last_active_object(session: BlenderSession) -> None:
    session.set_last_active_object("Sphere")
    result = parse("удали шар", session)
    assert result == ParsedCommand("delete_object", {"name": "Sphere"})


def test_move_object_with_three_numbers(session: BlenderSession) -> None:
    result = parse("передвинь Cube на 1, 2, 3", session)
    assert result == ParsedCommand("move_object", {"name": "Cube", "location": [1.0, 2.0, 3.0]})


def test_move_object_with_single_number_defaults_to_z_axis(session: BlenderSession) -> None:
    result = parse("перемести Cube на 5", session)
    assert result == ParsedCommand("move_object", {"name": "Cube", "location": [0.0, 0.0, 5.0]})


def test_rotate_object(session: BlenderSession) -> None:
    result = parse("поверни Cube на 90", session)
    assert result == ParsedCommand("rotate_object", {"name": "Cube", "rotation": [0.0, 0.0, 90.0]})


def test_scale_object_bigger(session: BlenderSession) -> None:
    result = parse("сделай Cube больше", session)
    assert result == ParsedCommand("scale_object", {"name": "Cube", "scale_factor": 1.5})


def test_scale_object_smaller(session: BlenderSession) -> None:
    result = parse("сделай Cube меньше", session)
    assert result == ParsedCommand("scale_object", {"name": "Cube", "scale_factor": 1 / 1.5})


def test_scale_object_by_explicit_factor(session: BlenderSession) -> None:
    result = parse("масштабируй Cube в 2", session)
    assert result == ParsedCommand("scale_object", {"name": "Cube", "scale_factor": 2.0})


def test_duplicate_object(session: BlenderSession) -> None:
    result = parse("дублируй Cube", session)
    assert result == ParsedCommand("duplicate_object", {"name": "Cube"})


def test_rename_object(session: BlenderSession) -> None:
    result = parse("переименуй Cube в Table", session)
    assert result == ParsedCommand("rename_object", {"old_name": "Cube", "new_name": "Table"})


def test_select_object(session: BlenderSession) -> None:
    result = parse("выдели Cube", session)
    assert result == ParsedCommand("select_object", {"name": "Cube"})


def test_add_modifier(session: BlenderSession) -> None:
    result = parse("примени модификатор subdivision к Cube", session)
    assert result == ParsedCommand(
        "add_modifier", {"object_name": "Cube", "modifier_type": "SUBSURF", "settings": {}}
    )


def test_add_modifier_with_unknown_name_uppercases_it(session: BlenderSession) -> None:
    result = parse("добавь модификатор weld к Cube", session)
    assert result == ParsedCommand(
        "add_modifier", {"object_name": "Cube", "modifier_type": "WELD", "settings": {}}
    )


def test_remove_modifier(session: BlenderSession) -> None:
    result = parse("удали модификатор булеан у Cube", session)
    assert result == ParsedCommand("remove_modifier", {"object_name": "Cube", "modifier_name": "BOOLEAN"})


def test_apply_modifier_with_explicit_object(session: BlenderSession) -> None:
    result = parse("запеки модификатор bevel на Cube", session)
    assert result == ParsedCommand("apply_modifier", {"object_name": "Cube", "modifier_name": "BEVEL"})


def test_apply_modifier_without_object_uses_pronoun_default(session: BlenderSession) -> None:
    session.set_last_active_object("Cube")
    result = parse("запеки модификатор array", session)
    assert result == ParsedCommand("apply_modifier", {"object_name": "Cube", "modifier_name": "ARRAY"})


def test_create_material(session: BlenderSession) -> None:
    result = parse("создай материал Красный", session)
    assert result == ParsedCommand("create_material", {"name": "Красный"})


def test_assign_material(session: BlenderSession) -> None:
    result = parse("назначь материал Красный на Cube", session)
    assert result == ParsedCommand("assign_material", {"object_name": "Cube", "material_name": "Красный"})


def test_switch_mode_known(session: BlenderSession) -> None:
    result = parse("переключись в режим редактирования", session)
    assert result == ParsedCommand("switch_mode", {"mode": "EDIT"})


def test_switch_mode_unknown_falls_through(session: BlenderSession) -> None:
    assert parse("переключись в режим полёта", session) is None


def test_switch_viewport_shading(session: BlenderSession) -> None:
    result = parse("переключи вьюпорт в каркасный режим", session)
    assert result == ParsedCommand("switch_viewport_shading", {"shading": "WIREFRAME"})


def test_insert_keyframe_with_object_and_frame(session: BlenderSession) -> None:
    result = parse("поставь ключевой кадр для Cube на кадре 24", session)
    assert result == ParsedCommand(
        "insert_keyframe", {"object_name": "Cube", "property": "location", "frame": 24}
    )


def test_insert_keyframe_without_object_uses_pronoun_default(session: BlenderSession) -> None:
    session.set_last_active_object("Cube")
    result = parse("вставь ключевой кадр", session)
    assert result == ParsedCommand("insert_keyframe", {"object_name": "Cube", "property": "location"})


def test_set_current_frame(session: BlenderSession) -> None:
    result = parse("перейди на кадр 42", session)
    assert result == ParsedCommand("set_current_frame", {"frame": 42})


def test_start_render(session: BlenderSession) -> None:
    assert parse("запусти рендер", session) == ParsedCommand("start_render", {})


def test_get_render_status(session: BlenderSession) -> None:
    assert parse("статус рендера", session) == ParsedCommand("get_render_status", {})


def test_save_file_without_path(session: BlenderSession) -> None:
    assert parse("сохрани файл", session) == ParsedCommand("save_file", {})


def test_save_file_with_path(session: BlenderSession) -> None:
    result = parse("сохрани файл как /tmp/scene.blend", session)
    assert result == ParsedCommand("save_file", {"path": "/tmp/scene.blend"})


def test_open_file(session: BlenderSession) -> None:
    result = parse("открой файл /tmp/scene.blend", session)
    assert result == ParsedCommand("open_file", {"path": "/tmp/scene.blend"})


def test_undo(session: BlenderSession) -> None:
    assert parse("отмени", session) == ParsedCommand("undo", {})


def test_redo(session: BlenderSession) -> None:
    assert parse("повтори", session) == ParsedCommand("redo", {})


def test_matching_is_case_insensitive(session: BlenderSession) -> None:
    assert parse("СОЗДАЙ КУБ", session) == ParsedCommand("create_primitive", {"type": "cube"})


def test_trailing_punctuation_is_stripped(session: BlenderSession) -> None:
    assert parse("отмени!", session) == ParsedCommand("undo", {})
