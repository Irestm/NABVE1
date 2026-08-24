from __future__ import annotations

import pytest

from modules.office_impress import command_parser


@pytest.mark.asyncio
async def test_open_presentation_blank() -> None:
    parsed = await command_parser.parse_command("открой презентацию")
    assert parsed == command_parser.ParsedImpressCommand(action="open_presentation", params={})


@pytest.mark.asyncio
async def test_open_presentation_with_path() -> None:
    parsed = await command_parser.parse_command("открой презентацию /home/user/slides.pptx")
    assert parsed == command_parser.ParsedImpressCommand(
        action="open_presentation", params={"path": "/home/user/slides.pptx"}
    )


@pytest.mark.asyncio
async def test_save_presentation_no_path() -> None:
    parsed = await command_parser.parse_command("сохрани презентацию")
    assert parsed == command_parser.ParsedImpressCommand(action="save_presentation", params={})


@pytest.mark.asyncio
async def test_save_presentation_as() -> None:
    parsed = await command_parser.parse_command("сохрани как /tmp/out.pptx")
    assert parsed == command_parser.ParsedImpressCommand(
        action="save_presentation", params={"path": "/tmp/out.pptx"}
    )


@pytest.mark.asyncio
async def test_close_presentation_with_save() -> None:
    parsed = await command_parser.parse_command("закрой презентацию с сохранением")
    assert parsed == command_parser.ParsedImpressCommand(action="close_presentation", params={"save": True})


@pytest.mark.asyncio
async def test_undo() -> None:
    parsed = await command_parser.parse_command("отмени")
    assert parsed == command_parser.ParsedImpressCommand(action="impress_undo", params={})


@pytest.mark.asyncio
async def test_redo() -> None:
    parsed = await command_parser.parse_command("повтори")
    assert parsed == command_parser.ParsedImpressCommand(action="impress_redo", params={})


@pytest.mark.asyncio
async def test_add_slide_no_index() -> None:
    parsed = await command_parser.parse_command("добавь слайд")
    assert parsed == command_parser.ParsedImpressCommand(action="add_slide", params={})


@pytest.mark.asyncio
async def test_add_slide_with_index() -> None:
    parsed = await command_parser.parse_command("добавь слайд номер 3")
    assert parsed == command_parser.ParsedImpressCommand(action="add_slide", params={"index": 3})


@pytest.mark.asyncio
async def test_delete_slide() -> None:
    parsed = await command_parser.parse_command("удали слайд 2")
    assert parsed == command_parser.ParsedImpressCommand(action="delete_slide", params={"index": 2})


@pytest.mark.asyncio
async def test_duplicate_slide() -> None:
    parsed = await command_parser.parse_command("дублируй слайд 4")
    assert parsed == command_parser.ParsedImpressCommand(action="duplicate_slide", params={"index": 4})


@pytest.mark.asyncio
async def test_go_to_slide() -> None:
    parsed = await command_parser.parse_command("перейди на слайд 5")
    assert parsed == command_parser.ParsedImpressCommand(action="go_to_slide", params={"index": 5})


@pytest.mark.asyncio
async def test_set_slide_title_current() -> None:
    parsed = await command_parser.parse_command("заголовок введение")
    assert parsed == command_parser.ParsedImpressCommand(action="set_slide_title", params={"text": "введение"})


@pytest.mark.asyncio
async def test_set_slide_title_with_index() -> None:
    parsed = await command_parser.parse_command("заголовок слайда 2 итоги")
    assert parsed == command_parser.ParsedImpressCommand(
        action="set_slide_title", params={"text": "итоги", "index": 2}
    )


@pytest.mark.asyncio
async def test_set_slide_body_single_line() -> None:
    parsed = await command_parser.parse_command("текст слайда сегодня мы обсудим план")
    assert parsed == command_parser.ParsedImpressCommand(
        action="set_slide_body", params={"text": "сегодня мы обсудим план"}
    )


@pytest.mark.asyncio
async def test_set_slide_body_bullet_items() -> None:
    parsed = await command_parser.parse_command("содержимое слайда первый пункт, второй пункт")
    assert parsed == command_parser.ParsedImpressCommand(
        action="set_slide_body", params={"items": ["первый пункт", "второй пункт"]}
    )


@pytest.mark.asyncio
async def test_set_slide_layout_blank() -> None:
    parsed = await command_parser.parse_command("сделай слайд 3 пустым")
    assert parsed == command_parser.ParsedImpressCommand(
        action="set_slide_layout", params={"layout": "blank", "index": 3}
    )


@pytest.mark.asyncio
async def test_set_slide_title_format_bold() -> None:
    parsed = await command_parser.parse_command("сделай заголовок жирным")
    assert parsed is not None
    assert parsed.action == "set_slide_text_format"
    assert parsed.params == {"target": "title", "bold": True}


@pytest.mark.asyncio
async def test_set_slide_body_format_with_index_and_color() -> None:
    parsed = await command_parser.parse_command("сделай текст слайда 2 красным")
    assert parsed is not None
    assert parsed.action == "set_slide_text_format"
    assert parsed.params["target"] == "body"
    assert parsed.params["index"] == 2
    assert parsed.params["color"] == "FF0000"


@pytest.mark.asyncio
async def test_unrecognized_falls_through_to_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse_with_ai(text: str) -> None:
        return None

    monkeypatch.setattr(command_parser, "_parse_with_ai", fake_parse_with_ai)
    parsed = await command_parser.parse_command("расскажи анекдот")
    assert parsed is None
