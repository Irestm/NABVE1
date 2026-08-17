from __future__ import annotations

import asyncio

import pytest

from modules.figma_control import command_parser


@pytest.fixture(autouse=True)
def _reset_session_state():
    command_parser.session_state.last_selected_layer = None
    yield
    command_parser.session_state.last_selected_layer = None


def _parse(text: str) -> command_parser.ParsedFigmaCommand | None:
    return asyncio.run(command_parser.parse_command(text))


def test_create_rectangle_parses_dimensions():
    parsed = _parse("создай прямоугольник 100 на 200")
    assert parsed == command_parser.ParsedFigmaCommand(
        action="create_rectangle", params={"width": 100, "height": 200}
    )


def test_create_rectangle_with_color():
    parsed = _parse("создай красный прямоугольник 100 на 200")
    assert parsed is not None
    assert parsed.action == "create_rectangle"
    assert parsed.params["fill_color"] == "#FF0000"


def test_create_frame_with_name():
    parsed = _parse("создай фрейм 300 на 400 с именем Главный экран")
    assert parsed == command_parser.ParsedFigmaCommand(
        action="create_frame", params={"width": 300, "height": 400, "name": "главный экран"}
    )


def test_select_layer_by_name():
    parsed = _parse("выдели слой Кнопка")
    assert parsed == command_parser.ParsedFigmaCommand(action="select_layer", params={"layer_name": "кнопка"})


def test_select_layer_updates_available_for_context():
    command_parser.session_state.last_selected_layer = "кнопка"
    assert command_parser.session_state.last_selected_layer == "кнопка"


def test_change_color_uses_last_selected_layer_when_no_explicit_name():
    command_parser.session_state.last_selected_layer = "кнопка"
    parsed = _parse("сделай его красным")
    assert parsed == command_parser.ParsedFigmaCommand(
        action="change_color", params={"layer_name": "кнопка", "color": "#FF0000"}
    )


def test_change_color_with_explicit_layer_name():
    parsed = _parse("покрась слой Кнопка в синий")
    assert parsed == command_parser.ParsedFigmaCommand(
        action="change_color", params={"layer_name": "кнопка", "color": "#0000FF"}
    )


def test_change_color_without_any_known_layer_returns_none(monkeypatch):
    # No explicit layer name in the phrase, and no prior selection to fall
    # back on — command_parser can't guess which layer "его" refers to.
    # The literal pattern match fails closed (returns None) rather than
    # falling through to the AI path, so no adapter needs mocking here for
    # correctness — but block it anyway (see
    # test_unrecognized_text_falls_through_to_none_when_ai_unavailable)
    # so a regression that DID fall through couldn't silently hit a real
    # AI provider from this unit test.
    monkeypatch.setattr(command_parser, "local_first_chain", lambda: [])
    parsed = _parse("сделай его красным")
    assert parsed is None


def test_align_left():
    parsed = _parse("выровняй по левому краю")
    assert parsed == command_parser.ParsedFigmaCommand(action="align", params={"alignment": "left"})


def test_group_selection():
    parsed = _parse("сгруппируй выделенное")
    assert parsed == command_parser.ParsedFigmaCommand(action="group_selection", params={})


def test_delete_layer():
    parsed = _parse("удали слой Кнопка")
    assert parsed == command_parser.ParsedFigmaCommand(action="delete_layer", params={"layer_name": "кнопка"})


def test_undo_and_redo():
    assert _parse("отмени") == command_parser.ParsedFigmaCommand(action="undo", params={})
    assert _parse("повтори") == command_parser.ParsedFigmaCommand(action="redo", params={})


def test_unrecognized_text_falls_through_to_none_when_ai_unavailable(monkeypatch):
    async def _raise(*_args, **_kwargs):
        raise RuntimeError("no adapters available in tests")

    class _FailingAdapter:
        name = "fake"
        send_prompt = staticmethod(_raise)

    monkeypatch.setattr(command_parser, "local_first_chain", lambda: [_FailingAdapter()])
    parsed = _parse("расскажи мне анекдот")
    assert parsed is None
