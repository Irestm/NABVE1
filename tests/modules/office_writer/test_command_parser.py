from __future__ import annotations

import pytest

from modules.office_writer import command_parser


@pytest.mark.asyncio
async def test_open_document_blank() -> None:
    parsed = await command_parser.parse_command("открой ворд")
    assert parsed is not None
    assert parsed.action == "open_document"
    assert parsed.params == {}


@pytest.mark.asyncio
async def test_open_document_with_path() -> None:
    parsed = await command_parser.parse_command("открой документ /home/user/report.docx")
    assert parsed is not None
    assert parsed.action == "open_document"
    assert parsed.params == {"path": "/home/user/report.docx"}


@pytest.mark.asyncio
async def test_save_document_no_path() -> None:
    parsed = await command_parser.parse_command("сохрани документ")
    assert parsed == command_parser.ParsedWriterCommand(action="save_document", params={})


@pytest.mark.asyncio
async def test_save_document_as() -> None:
    parsed = await command_parser.parse_command("сохрани как /tmp/out.docx")
    assert parsed is not None
    assert parsed.action == "save_document"
    assert parsed.params == {"path": "/tmp/out.docx"}


@pytest.mark.asyncio
async def test_close_document_with_save() -> None:
    parsed = await command_parser.parse_command("закрой документ с сохранением")
    assert parsed == command_parser.ParsedWriterCommand(action="close_document", params={"save": True})


@pytest.mark.asyncio
async def test_close_document_without_save() -> None:
    parsed = await command_parser.parse_command("закрой документ")
    assert parsed == command_parser.ParsedWriterCommand(action="close_document", params={"save": False})


@pytest.mark.asyncio
async def test_undo() -> None:
    parsed = await command_parser.parse_command("отмени")
    assert parsed == command_parser.ParsedWriterCommand(action="undo", params={})


@pytest.mark.asyncio
async def test_redo() -> None:
    parsed = await command_parser.parse_command("повтори")
    assert parsed == command_parser.ParsedWriterCommand(action="redo", params={})


@pytest.mark.asyncio
async def test_insert_text() -> None:
    parsed = await command_parser.parse_command("напиши привет мир")
    assert parsed == command_parser.ParsedWriterCommand(
        action="insert_text", params={"content": "привет мир"}
    )


@pytest.mark.asyncio
async def test_insert_text_append_at_end() -> None:
    parsed = await command_parser.parse_command("допиши ещё одно предложение")
    assert parsed == command_parser.ParsedWriterCommand(
        action="insert_text", params={"content": "ещё одно предложение", "position": "end"}
    )


@pytest.mark.asyncio
async def test_replace_selection() -> None:
    parsed = await command_parser.parse_command("замени выделенное на новый текст")
    assert parsed == command_parser.ParsedWriterCommand(
        action="replace_selection", params={"content": "новый текст"}
    )


@pytest.mark.asyncio
async def test_delete_selection() -> None:
    parsed = await command_parser.parse_command("удали выделенное")
    assert parsed == command_parser.ParsedWriterCommand(action="delete_selection", params={})


@pytest.mark.asyncio
async def test_insert_page_break() -> None:
    parsed = await command_parser.parse_command("новая страница")
    assert parsed == command_parser.ParsedWriterCommand(action="insert_page_break", params={})


@pytest.mark.asyncio
async def test_insert_table() -> None:
    parsed = await command_parser.parse_command("вставь таблицу 3 на 4")
    assert parsed == command_parser.ParsedWriterCommand(
        action="insert_table", params={"rows": 3, "cols": 4}
    )


@pytest.mark.asyncio
async def test_table_insert_row() -> None:
    parsed = await command_parser.parse_command("добавь строку в таблицу")
    assert parsed == command_parser.ParsedWriterCommand(action="table_insert_row", params={})


@pytest.mark.asyncio
async def test_table_insert_column() -> None:
    parsed = await command_parser.parse_command("добавь столбец")
    assert parsed == command_parser.ParsedWriterCommand(action="table_insert_column", params={})


@pytest.mark.asyncio
async def test_table_delete_row() -> None:
    parsed = await command_parser.parse_command("удали строку")
    assert parsed == command_parser.ParsedWriterCommand(action="table_delete_row", params={})


@pytest.mark.asyncio
async def test_table_delete_column() -> None:
    parsed = await command_parser.parse_command("удали колонку")
    assert parsed == command_parser.ParsedWriterCommand(action="table_delete_column", params={})


@pytest.mark.asyncio
async def test_insert_heading_default_level() -> None:
    parsed = await command_parser.parse_command("заголовок введение")
    assert parsed == command_parser.ParsedWriterCommand(
        action="insert_heading", params={"text": "введение", "level": 1}
    )


@pytest.mark.asyncio
async def test_insert_heading_explicit_level() -> None:
    parsed = await command_parser.parse_command("вставь заголовок уровня 3 детали")
    assert parsed == command_parser.ParsedWriterCommand(
        action="insert_heading", params={"text": "детали", "level": 3}
    )


@pytest.mark.asyncio
async def test_insert_subheading() -> None:
    parsed = await command_parser.parse_command("подзаголовок детали")
    assert parsed == command_parser.ParsedWriterCommand(
        action="insert_heading", params={"text": "детали", "level": 2}
    )


@pytest.mark.asyncio
async def test_insert_list_bulleted() -> None:
    parsed = await command_parser.parse_command("вставь список: первый пункт, второй пункт")
    assert parsed == command_parser.ParsedWriterCommand(
        action="insert_list", params={"items": ["первый пункт", "второй пункт"], "ordered": False}
    )


@pytest.mark.asyncio
async def test_insert_list_numbered() -> None:
    parsed = await command_parser.parse_command("вставь нумерованный список первое, второе")
    assert parsed == command_parser.ParsedWriterCommand(
        action="insert_list", params={"items": ["первое", "второе"], "ordered": True}
    )


@pytest.mark.asyncio
async def test_set_format_bold() -> None:
    parsed = await command_parser.parse_command("сделай текст жирным")
    assert parsed is not None
    assert parsed.action == "set_format"
    assert parsed.params == {"bold": True}


@pytest.mark.asyncio
async def test_set_format_remove_bold() -> None:
    parsed = await command_parser.parse_command("убери жирный")
    assert parsed == command_parser.ParsedWriterCommand(action="set_format", params={"bold": False})


@pytest.mark.asyncio
async def test_set_format_combined() -> None:
    parsed = await command_parser.parse_command("сделай текст жирным и по центру")
    assert parsed is not None
    assert parsed.action == "set_format"
    assert parsed.params == {"bold": True, "align": "center"}


@pytest.mark.asyncio
async def test_set_format_font_size() -> None:
    parsed = await command_parser.parse_command("размер шрифта 16")
    assert parsed == command_parser.ParsedWriterCommand(action="set_format", params={"font_size": 16})


@pytest.mark.asyncio
async def test_set_format_color() -> None:
    parsed = await command_parser.parse_command("сделай текст красным")
    assert parsed == command_parser.ParsedWriterCommand(action="set_format", params={"color": "FF0000"})


@pytest.mark.asyncio
async def test_list_headings() -> None:
    parsed = await command_parser.parse_command("покажи структуру документа")
    assert parsed == command_parser.ParsedWriterCommand(action="list_headings", params={})


@pytest.mark.asyncio
async def test_unrecognized_falls_through_to_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse_with_ai(text: str) -> None:
        return None

    monkeypatch.setattr(command_parser, "_parse_with_ai", fake_parse_with_ai)
    parsed = await command_parser.parse_command("расскажи анекдот")
    assert parsed is None
