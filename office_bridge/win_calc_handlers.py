"""win32com action handlers for the Windows Jarvis <-> Excel bridge — the
Windows counterpart of office_bridge/calc_handlers.py.

Same ACTIONS vocabulary/params as the Linux/UNO side, reimplemented against
Excel's COM object model. Not exercised against a real Excel install — see
office_bridge/server_win.py's module docstring.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from win_session import OfficeCommandError, WinOfficeSession, bgr_color

# xlUnderlineStyleNone / xlUnderlineStyleSingle.
_XL_UNDERLINE_NONE = -4142
_XL_UNDERLINE_SINGLE = 2
# xlHAlignLeft / xlHAlignCenter / xlHAlignRight / xlHAlignJustify.
_XL_ALIGN_BY_NAME: dict[str, int] = {
    "left": -4131, "center": -4108, "right": -4152, "justify": -4130,
}


def _require(params: dict[str, Any], key: str) -> Any:
    value = params.get(key)
    if value in (None, ""):
        raise OfficeCommandError(f"Не указан обязательный параметр '{key}'")
    return value


def _abs_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _active_sheet(session: WinOfficeSession) -> Any:
    return session.require_excel_workbook().ActiveSheet


def _column_number(letters: str) -> int:
    """Column letters ("A", "AB", ...) -> 1-based column number, same
    base-26 scheme as calc_handlers.py's own _column_index (which is
    0-based there — this stays 1-based since every use site here builds an
    Excel Range/Columns() reference, which is 1-based natively)."""
    number = 0
    for ch in letters.strip():
        if not ch.isalpha():
            raise OfficeCommandError(f"Некорректное имя столбца: {letters}")
        number = number * 26 + (ord(ch.upper()) - ord("A") + 1)
    return number


def _open_spreadsheet(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    path = params.get("path")
    if path and os.path.exists(_abs_path(path)):
        workbook = session.excel_app.Workbooks.Open(_abs_path(path))
    else:
        # Same "never Open() a path that doesn't exist yet" reasoning as
        # win_writer_handlers.py's _open_document.
        workbook = session.excel_app.Workbooks.Add()
        if path:
            workbook.SaveAs(_abs_path(path))
    session.excel_workbook = workbook
    return {"opened": path or "новая таблица"}


def _save_spreadsheet(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    workbook = session.require_excel_workbook()
    path = params.get("path")
    if path:
        workbook.SaveAs(_abs_path(path))
    else:
        if not workbook.Path:
            raise OfficeCommandError("У таблицы ещё нет пути на диске — укажи, куда сохранить.")
        workbook.Save()
    return {}


def _close_spreadsheet(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    workbook = session.require_excel_workbook()
    if params.get("save"):
        _save_spreadsheet(session, {})
    workbook.Close(SaveChanges=False)
    session.excel_workbook = None
    return {}


def _calc_undo(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    # Excel's Application.Undo() over COM automation is a known weak spot —
    # unlike Word, many Excel operations (formatting, sheet structure
    # changes) simply aren't on its undo stack when driven by automation, so
    # this can silently no-op for some actions. Calling it is still strictly
    # better than not offering undo at all, but flag this honestly rather
    # than implying full parity with Writer's undo.
    session.require_excel_workbook()
    session.excel_app.Undo()
    return {}


def _calc_redo(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    session.require_excel_workbook()
    session.excel_app.Redo()
    return {}


def _set_cell_value(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    sheet = _active_sheet(session)
    cell_name = _require(params, "cell")
    value = _require(params, "value")
    cell = sheet.Range(cell_name)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        cell.Value = float(value)
        return {}
    text = str(value)
    try:
        cell.Value = float(text.replace(",", "."))
    except ValueError:
        cell.Value = text
    return {}


def _clear_range(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    sheet = _active_sheet(session)
    range_name = _require(params, "range")
    # ClearContents wipes values/formulas but leaves formatting/comments in
    # place — the same intent as calc_handlers.py's explicit CellFlags mask.
    sheet.Range(range_name).ClearContents()
    return {}


def _set_formula(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    sheet = _active_sheet(session)
    cell_name = _require(params, "cell")
    formula = str(_require(params, "formula"))
    if not formula.startswith("="):
        formula = "=" + formula
    sheet.Range(cell_name).Formula = formula
    return {}


def _set_cell_format(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    sheet = _active_sheet(session)
    range_name = _require(params, "range")
    cell_range = sheet.Range(range_name)
    if "bold" in params:
        cell_range.Font.Bold = bool(params["bold"])
    if "italic" in params:
        cell_range.Font.Italic = bool(params["italic"])
    if "underline" in params:
        cell_range.Font.Underline = _XL_UNDERLINE_SINGLE if params["underline"] else _XL_UNDERLINE_NONE
    if "font_size" in params:
        cell_range.Font.Size = float(params["font_size"])
    if "color" in params:
        cell_range.Font.Color = bgr_color(params["color"])
    if "fill_color" in params:
        cell_range.Interior.Color = bgr_color(params["fill_color"])
    if "align" in params:
        alignment = _XL_ALIGN_BY_NAME.get(str(params["align"]).lower())
        if alignment is None:
            raise OfficeCommandError(f"Неизвестное выравнивание: {params['align']}")
        cell_range.HorizontalAlignment = alignment
    return {}


def _sheet_insert_row(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    sheet = _active_sheet(session)
    row = int(_require(params, "row"))
    count = int(params.get("count", 1))
    sheet.Range(sheet.Rows(row), sheet.Rows(row + count - 1)).Insert()
    return {}


def _sheet_insert_column(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    sheet = _active_sheet(session)
    column = _column_number(str(_require(params, "column")))
    count = int(params.get("count", 1))
    sheet.Range(sheet.Columns(column), sheet.Columns(column + count - 1)).Insert()
    return {}


def _sheet_delete_row(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    sheet = _active_sheet(session)
    row = int(_require(params, "row"))
    count = int(params.get("count", 1))
    sheet.Range(sheet.Rows(row), sheet.Rows(row + count - 1)).Delete()
    return {}


def _sheet_delete_column(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    sheet = _active_sheet(session)
    column = _column_number(str(_require(params, "column")))
    count = int(params.get("count", 1))
    sheet.Range(sheet.Columns(column), sheet.Columns(column + count - 1)).Delete()
    return {}


def _sheet_add(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    workbook = session.require_excel_workbook()
    sheets = workbook.Sheets
    name = params.get("name") or f"Лист{sheets.Count + 1}"
    new_sheet = sheets.Add(After=sheets(sheets.Count))
    new_sheet.Name = name
    return {"name": name}


def _sheet_rename(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    workbook = session.require_excel_workbook()
    new_name = _require(params, "new_name")
    old_name = params.get("old_name")
    sheet = workbook.Sheets(old_name) if old_name else _active_sheet(session)
    sheet.Name = new_name
    return {}


def _sheet_switch(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    workbook = session.require_excel_workbook()
    name = _require(params, "name")
    existing_names = [sheet.Name for sheet in workbook.Sheets]
    if name not in existing_names:
        raise OfficeCommandError(f"Листа '{name}' не существует")
    workbook.Sheets(name).Activate()
    return {}


ACTIONS: dict[str, Callable[[WinOfficeSession, dict[str, Any]], dict[str, Any]]] = {
    "open_spreadsheet": _open_spreadsheet,
    "save_spreadsheet": _save_spreadsheet,
    "close_spreadsheet": _close_spreadsheet,
    "calc_undo": _calc_undo,
    "calc_redo": _calc_redo,
    "set_cell_value": _set_cell_value,
    "clear_range": _clear_range,
    "set_formula": _set_formula,
    "set_cell_format": _set_cell_format,
    "sheet_insert_row": _sheet_insert_row,
    "sheet_insert_column": _sheet_insert_column,
    "sheet_delete_row": _sheet_delete_row,
    "sheet_delete_column": _sheet_delete_column,
    "sheet_add": _sheet_add,
    "sheet_rename": _sheet_rename,
    "sheet_switch": _sheet_switch,
}
