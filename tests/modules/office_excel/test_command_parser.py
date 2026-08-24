from __future__ import annotations

import pytest

from modules.office_excel import command_parser


@pytest.mark.asyncio
async def test_open_spreadsheet_blank() -> None:
    parsed = await command_parser.parse_command("открой эксель")
    assert parsed == command_parser.ParsedExcelCommand(action="open_spreadsheet", params={})


@pytest.mark.asyncio
async def test_open_spreadsheet_with_path() -> None:
    parsed = await command_parser.parse_command("открой таблицу /home/user/budget.xlsx")
    assert parsed == command_parser.ParsedExcelCommand(
        action="open_spreadsheet", params={"path": "/home/user/budget.xlsx"}
    )


@pytest.mark.asyncio
async def test_save_spreadsheet_no_path() -> None:
    parsed = await command_parser.parse_command("сохрани таблицу")
    assert parsed == command_parser.ParsedExcelCommand(action="save_spreadsheet", params={})


@pytest.mark.asyncio
async def test_save_spreadsheet_as() -> None:
    parsed = await command_parser.parse_command("сохрани как /tmp/out.xlsx")
    assert parsed == command_parser.ParsedExcelCommand(
        action="save_spreadsheet", params={"path": "/tmp/out.xlsx"}
    )


@pytest.mark.asyncio
async def test_close_spreadsheet_with_save() -> None:
    parsed = await command_parser.parse_command("закрой таблицу с сохранением")
    assert parsed == command_parser.ParsedExcelCommand(action="close_spreadsheet", params={"save": True})


@pytest.mark.asyncio
async def test_close_spreadsheet_without_save() -> None:
    parsed = await command_parser.parse_command("закрой файл")
    assert parsed == command_parser.ParsedExcelCommand(action="close_spreadsheet", params={"save": False})


@pytest.mark.asyncio
async def test_undo() -> None:
    parsed = await command_parser.parse_command("отмени")
    assert parsed == command_parser.ParsedExcelCommand(action="calc_undo", params={})


@pytest.mark.asyncio
async def test_redo() -> None:
    parsed = await command_parser.parse_command("повтори")
    assert parsed == command_parser.ParsedExcelCommand(action="calc_redo", params={})


@pytest.mark.asyncio
async def test_set_cell_value_text() -> None:
    parsed = await command_parser.parse_command("впиши в А1 итого")
    assert parsed == command_parser.ParsedExcelCommand(
        action="set_cell_value", params={"cell": "A1", "value": "итого"}
    )


@pytest.mark.asyncio
async def test_set_cell_value_number() -> None:
    parsed = await command_parser.parse_command("впиши в B2 250")
    assert parsed == command_parser.ParsedExcelCommand(
        action="set_cell_value", params={"cell": "B2", "value": 250.0}
    )


@pytest.mark.asyncio
async def test_set_cell_value_decimal_with_comma() -> None:
    parsed = await command_parser.parse_command("впиши в C3 12,5")
    assert parsed == command_parser.ParsedExcelCommand(
        action="set_cell_value", params={"cell": "C3", "value": 12.5}
    )


@pytest.mark.asyncio
async def test_clear_range() -> None:
    parsed = await command_parser.parse_command("очисти диапазон A1:B10")
    assert parsed == command_parser.ParsedExcelCommand(action="clear_range", params={"range": "A1:B10"})


@pytest.mark.asyncio
async def test_set_formula() -> None:
    parsed = await command_parser.parse_command("формула в A4 сумма от A2 до A3")
    assert parsed == command_parser.ParsedExcelCommand(
        action="set_formula", params={"cell": "A4", "formula": "сумма от a2 до a3"}
    )


@pytest.mark.asyncio
async def test_sheet_insert_row() -> None:
    parsed = await command_parser.parse_command("добавь строку 5")
    assert parsed == command_parser.ParsedExcelCommand(action="sheet_insert_row", params={"row": 5})


@pytest.mark.asyncio
async def test_sheet_insert_column() -> None:
    parsed = await command_parser.parse_command("добавь столбец C")
    assert parsed == command_parser.ParsedExcelCommand(action="sheet_insert_column", params={"column": "C"})


@pytest.mark.asyncio
async def test_sheet_delete_row() -> None:
    parsed = await command_parser.parse_command("удали строку 3")
    assert parsed == command_parser.ParsedExcelCommand(action="sheet_delete_row", params={"row": 3})


@pytest.mark.asyncio
async def test_sheet_delete_column() -> None:
    parsed = await command_parser.parse_command("удали столбец B")
    assert parsed == command_parser.ParsedExcelCommand(action="sheet_delete_column", params={"column": "B"})


@pytest.mark.asyncio
async def test_sheet_add_named() -> None:
    parsed = await command_parser.parse_command("добавь лист с именем отчёт")
    assert parsed == command_parser.ParsedExcelCommand(action="sheet_add", params={"name": "отчёт"})


@pytest.mark.asyncio
async def test_sheet_add_unnamed() -> None:
    parsed = await command_parser.parse_command("добавь лист")
    assert parsed == command_parser.ParsedExcelCommand(action="sheet_add", params={})


@pytest.mark.asyncio
async def test_sheet_rename_active() -> None:
    parsed = await command_parser.parse_command("переименуй лист в итоги")
    assert parsed == command_parser.ParsedExcelCommand(action="sheet_rename", params={"new_name": "итоги"})


@pytest.mark.asyncio
async def test_sheet_switch() -> None:
    parsed = await command_parser.parse_command("перейди на лист итоги")
    assert parsed == command_parser.ParsedExcelCommand(action="sheet_switch", params={"name": "итоги"})


@pytest.mark.asyncio
async def test_set_cell_format_direct_bold() -> None:
    parsed = await command_parser.parse_command("сделай А1 жирным")
    assert parsed is not None
    assert parsed.action == "set_cell_format"
    assert parsed.params == {"range": "A1", "bold": True}


@pytest.mark.asyncio
async def test_set_cell_format_range_with_align_and_fill() -> None:
    parsed = await command_parser.parse_command("сделай ячейку A1:B2 по центру с заливкой жёлтый")
    assert parsed is not None
    assert parsed.action == "set_cell_format"
    assert parsed.params["range"] == "A1:B2"
    assert parsed.params["align"] == "center"
    assert parsed.params["fill_color"] == "FFFF00"


@pytest.mark.asyncio
async def test_cyrillic_lookalike_cell_ref_normalized() -> None:
    # STT is likely to transliterate Latin column letters into
    # visually-identical Cyrillic ones ("а1" instead of "a1").
    parsed = await command_parser.parse_command("впиши в а1 привет")
    assert parsed == command_parser.ParsedExcelCommand(
        action="set_cell_value", params={"cell": "A1", "value": "привет"}
    )


@pytest.mark.asyncio
async def test_unrecognized_falls_through_to_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse_with_ai(text: str) -> None:
        return None

    monkeypatch.setattr(command_parser, "_parse_with_ai", fake_parse_with_ai)
    parsed = await command_parser.parse_command("расскажи анекдот")
    assert parsed is None
