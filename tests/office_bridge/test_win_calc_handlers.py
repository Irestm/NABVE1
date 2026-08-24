from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import win_calc_handlers as handlers
from win_session import OfficeCommandError, WinOfficeSession


def _session_with_workbook() -> tuple[WinOfficeSession, MagicMock, MagicMock]:
    session = WinOfficeSession()
    excel_app = MagicMock()
    workbook = MagicMock()
    workbook.Path = "/tmp/x.xlsx"
    session.excel_app = excel_app
    session.excel_workbook = workbook
    return session, excel_app, workbook


def test_open_spreadsheet_opens_existing_path(tmp_path) -> None:
    path = tmp_path / "existing.xlsx"
    path.write_text("x")
    session = WinOfficeSession()
    session.excel_app = MagicMock()

    handlers.ACTIONS["open_spreadsheet"](session, {"path": str(path)})

    session.excel_app.Workbooks.Open.assert_called_once_with(str(path))
    session.excel_app.Workbooks.Add.assert_not_called()


def test_open_spreadsheet_creates_and_saves_when_missing(tmp_path) -> None:
    path = tmp_path / "new.xlsx"
    session = WinOfficeSession()
    session.excel_app = MagicMock()

    handlers.ACTIONS["open_spreadsheet"](session, {"path": str(path)})

    new_workbook = session.excel_app.Workbooks.Add.return_value
    new_workbook.SaveAs.assert_called_once_with(str(path))


def test_save_spreadsheet_without_path_requires_existing_location() -> None:
    session, _, workbook = _session_with_workbook()
    workbook.Path = ""
    with pytest.raises(OfficeCommandError, match="ещё нет пути"):
        handlers.ACTIONS["save_spreadsheet"](session, {})


def test_close_spreadsheet_closes_without_prompting() -> None:
    session, _, workbook = _session_with_workbook()
    handlers.ACTIONS["close_spreadsheet"](session, {})
    workbook.Close.assert_called_once_with(SaveChanges=False)
    assert session.excel_workbook is None


def test_set_cell_value_numeric_string_becomes_float() -> None:
    session, _, workbook = _session_with_workbook()
    sheet = workbook.ActiveSheet

    handlers.ACTIONS["set_cell_value"](session, {"cell": "A1", "value": "3,5"})

    assert sheet.Range.return_value.Value == 3.5


def test_set_cell_value_non_numeric_string_stays_text() -> None:
    session, _, workbook = _session_with_workbook()
    sheet = workbook.ActiveSheet

    handlers.ACTIONS["set_cell_value"](session, {"cell": "A1", "value": "привет"})

    assert sheet.Range.return_value.Value == "привет"


def test_set_cell_value_numeric_bypasses_string_parsing() -> None:
    session, _, workbook = _session_with_workbook()
    sheet = workbook.ActiveSheet

    handlers.ACTIONS["set_cell_value"](session, {"cell": "A1", "value": 7})

    assert sheet.Range.return_value.Value == 7.0


def test_clear_range_uses_clear_contents_not_clear() -> None:
    session, _, workbook = _session_with_workbook()
    handlers.ACTIONS["clear_range"](session, {"range": "A1:B2"})
    workbook.ActiveSheet.Range.return_value.ClearContents.assert_called_once()


def test_set_formula_adds_leading_equals_if_missing() -> None:
    session, _, workbook = _session_with_workbook()
    handlers.ACTIONS["set_formula"](session, {"cell": "A1", "formula": "SUM(B1:B2)"})
    assert workbook.ActiveSheet.Range.return_value.Formula == "=SUM(B1:B2)"


def test_set_cell_format_color_and_fill_color_are_bgr_converted() -> None:
    session, _, workbook = _session_with_workbook()
    cell_range = workbook.ActiveSheet.Range.return_value

    handlers.ACTIONS["set_cell_format"](session, {"range": "A1", "color": "#00FF00", "fill_color": "#0000FF"})

    assert cell_range.Font.Color == 0x00FF00  # green is byte-symmetric, sanity only
    assert cell_range.Interior.Color == 0xFF0000  # #0000FF -> BGR 0xFF0000


def test_set_cell_format_unknown_align_raises() -> None:
    session, _, _ = _session_with_workbook()
    with pytest.raises(OfficeCommandError, match="выравнивание"):
        handlers.ACTIONS["set_cell_format"](session, {"range": "A1", "align": "diagonal"})


def test_sheet_insert_row_uses_range_between_start_and_end_row() -> None:
    session, _, workbook = _session_with_workbook()
    sheet = workbook.ActiveSheet

    handlers.ACTIONS["sheet_insert_row"](session, {"row": 3, "count": 2})

    sheet.Rows.assert_any_call(3)
    sheet.Rows.assert_any_call(4)
    sheet.Range.return_value.Insert.assert_called_once()


def test_sheet_insert_column_parses_letter_to_number() -> None:
    session, _, workbook = _session_with_workbook()
    sheet = workbook.ActiveSheet

    handlers.ACTIONS["sheet_insert_column"](session, {"column": "B"})

    sheet.Columns.assert_any_call(2)


def test_column_number_rejects_non_letters() -> None:
    with pytest.raises(OfficeCommandError):
        handlers._column_number("1")


def test_sheet_add_names_and_renames_new_sheet() -> None:
    session, _, workbook = _session_with_workbook()
    workbook.Sheets.Count = 2

    result = handlers.ACTIONS["sheet_add"](session, {})

    assert result == {"name": "Лист3"}
    new_sheet = workbook.Sheets.Add.return_value
    assert new_sheet.Name == "Лист3"


def test_sheet_rename_defaults_to_active_sheet() -> None:
    session, _, workbook = _session_with_workbook()
    handlers.ACTIONS["sheet_rename"](session, {"new_name": "Итоги"})
    assert workbook.ActiveSheet.Name == "Итоги"


def test_sheet_switch_raises_for_unknown_sheet() -> None:
    session, _, workbook = _session_with_workbook()
    # Sheets must stay callable (Sheets(name) below) as well as iterable
    # (existing_names' list comprehension) — a plain list can't do both.
    sheet_a = MagicMock(Name="Sheet1")
    workbook.Sheets.__iter__.return_value = iter([sheet_a])
    with pytest.raises(OfficeCommandError, match="не существует"):
        handlers.ACTIONS["sheet_switch"](session, {"name": "Sheet2"})


def test_sheet_switch_activates_matching_sheet() -> None:
    session, _, workbook = _session_with_workbook()
    sheet_a = MagicMock(Name="Sheet1")
    workbook.Sheets.__iter__.return_value = iter([sheet_a])

    handlers.ACTIONS["sheet_switch"](session, {"name": "Sheet1"})

    workbook.Sheets.assert_called_with("Sheet1")
    workbook.Sheets.return_value.Activate.assert_called_once()
