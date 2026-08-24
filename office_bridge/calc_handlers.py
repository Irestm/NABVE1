"""UNO action handlers for the Jarvis <-> LibreOffice Calc bridge.

Same shape as writer_handlers.py — (session: OfficeSession, params: dict) ->
dict — but Calc addresses content by explicit cell/range names instead of a
view cursor: no "current selection" concept is needed here, since every
action that touches a cell already takes an explicit `cell`/`range` param,
which is both simpler than Writer's cursor model and closer to how a voice
command naturally names a spot in a spreadsheet ("впиши в А1 сто").
"""

from __future__ import annotations

import os
from typing import Any, Callable

import uno

from office_session import OfficeCommandError, OfficeSession, prop as _prop

_FILTER_BY_EXTENSION: dict[str, str] = {
    ".xlsx": "Calc MS Excel 2007 XML",
    ".xls": "MS Excel 97",
    ".ods": "calc8",
    ".csv": "Text - txt - csv (StarCalc)",
    ".pdf": "calc_pdf_Export",
}

_HORI_JUSTIFY_BY_NAME: dict[str, str] = {
    "left": "LEFT",
    "right": "RIGHT",
    "center": "CENTER",
    "justify": "BLOCK",
}

# com.sun.star.sheet.CellFlags is a constants group (plain ints, not an
# enum), same reasoning as writer_handlers.py's _PARAGRAPH_BREAK: VALUE=1,
# DATETIME=2, STRING=4, FORMULA=16 — everything clear_range should wipe,
# deliberately excluding STYLES/OBJECTS/ANNOTATION so formatting and
# comments survive a "clear the values" command.
_CLEAR_CONTENT_FLAGS = 1 | 2 | 4 | 16


def _require(params: dict[str, Any], key: str) -> Any:
    value = params.get(key)
    if value in (None, ""):
        raise OfficeCommandError(f"Не указан обязательный параметр '{key}'")
    return value


def _to_file_url(path: str) -> str:
    return uno.systemPathToFileUrl(os.path.abspath(os.path.expanduser(path)))


def _active_sheet(document: Any) -> Any:
    return document.getCurrentController().getActiveSheet()


def _column_index(letters: str) -> int:
    """Column letters ("A", "AB", ...) -> 0-based index, same base-26
    scheme as writer_handlers.py's table cell-name parsing."""
    index = 0
    for ch in letters.strip():
        if not ch.isalpha():
            raise OfficeCommandError(f"Некорректное имя столбца: {letters}")
        index = index * 26 + (ord(ch.upper()) - ord("A") + 1)
    return index - 1


def _open_spreadsheet(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    path = params.get("path")
    if path and os.path.exists(os.path.abspath(os.path.expanduser(path))):
        document = session.desktop.loadComponentFromURL(
            _to_file_url(path), "_blank", 0, (_prop("Hidden", False),)
        )
    else:
        # loadComponentFromURL on a path that doesn't exist yet hangs
        # indefinitely rather than erroring — verified empirically
        # (writer_handlers.py hit the same issue first, see
        # AGENT_NOTES.md) — so always create blank and give it the
        # requested location via storeAsURL instead.
        document = session.desktop.loadComponentFromURL(
            "private:factory/scalc", "_blank", 0, (_prop("Hidden", False),)
        )
        if path:
            document.storeAsURL(_to_file_url(path), ())
    session.calc_document = document
    return {"opened": path or "новая таблица"}


def _save_spreadsheet(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_calc_document()
    path = params.get("path")
    if path:
        url = _to_file_url(path)
        filter_name = _FILTER_BY_EXTENSION.get(os.path.splitext(path)[1].lower(), "calc8")
        document.storeToURL(url, (_prop("FilterName", filter_name), _prop("Overwrite", True)))
    else:
        if not document.hasLocation():
            raise OfficeCommandError("У таблицы ещё нет пути на диске — укажи, куда сохранить.")
        document.store()
    return {}


def _close_spreadsheet(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_calc_document()
    if params.get("save"):
        _save_spreadsheet(session, {})
    document.close(False)
    session.calc_document = None
    return {}


def _calc_undo(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    session.require_calc_document().getUndoManager().undo()
    return {}


def _calc_redo(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    session.require_calc_document().getUndoManager().redo()
    return {}


def _set_cell_value(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_calc_document()
    cell_name = _require(params, "cell")
    value = _require(params, "value")
    cell = _active_sheet(document).getCellRangeByName(cell_name)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        cell.setValue(float(value))
        return {}
    text = str(value)
    try:
        cell.setValue(float(text.replace(",", ".")))
    except ValueError:
        cell.setString(text)
    return {}


def _clear_range(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_calc_document()
    range_name = _require(params, "range")
    _active_sheet(document).getCellRangeByName(range_name).clearContents(_CLEAR_CONTENT_FLAGS)
    return {}


def _set_formula(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_calc_document()
    cell_name = _require(params, "cell")
    formula = str(_require(params, "formula"))
    if not formula.startswith("="):
        formula = "=" + formula
    _active_sheet(document).getCellRangeByName(cell_name).setFormula(formula)
    return {}


def _set_cell_format(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_calc_document()
    range_name = _require(params, "range")
    cell_range = _active_sheet(document).getCellRangeByName(range_name)
    if "bold" in params:
        cell_range.CharWeight = 150.0 if params["bold"] else 100.0
    if "italic" in params:
        cell_range.CharPosture = uno.Enum(
            "com.sun.star.awt.FontSlant", "ITALIC" if params["italic"] else "NONE"
        )
    if "underline" in params:
        cell_range.CharUnderline = 1 if params["underline"] else 0
    if "font_size" in params:
        cell_range.CharHeight = float(params["font_size"])
    if "color" in params:
        cell_range.CharColor = int(str(params["color"]).lstrip("#"), 16)
    if "fill_color" in params:
        cell_range.CellBackColor = int(str(params["fill_color"]).lstrip("#"), 16)
    if "align" in params:
        alignment = _HORI_JUSTIFY_BY_NAME.get(str(params["align"]).lower())
        if alignment is None:
            raise OfficeCommandError(f"Неизвестное выравнивание: {params['align']}")
        cell_range.HoriJustify = uno.Enum("com.sun.star.table.CellHoriJustify", alignment)
    return {}


def _sheet_insert_row(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_calc_document()
    row = int(_require(params, "row"))
    _active_sheet(document).getRows().insertByIndex(row - 1, int(params.get("count", 1)))
    return {}


def _sheet_insert_column(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_calc_document()
    column_index = _column_index(str(_require(params, "column")))
    _active_sheet(document).getColumns().insertByIndex(column_index, int(params.get("count", 1)))
    return {}


def _sheet_delete_row(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_calc_document()
    row = int(_require(params, "row"))
    _active_sheet(document).getRows().removeByIndex(row - 1, int(params.get("count", 1)))
    return {}


def _sheet_delete_column(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_calc_document()
    column_index = _column_index(str(_require(params, "column")))
    _active_sheet(document).getColumns().removeByIndex(column_index, int(params.get("count", 1)))
    return {}


def _sheet_add(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_calc_document()
    sheets = document.getSheets()
    name = params.get("name") or f"Лист{sheets.Count + 1}"
    sheets.insertNewByName(name, sheets.Count)
    return {"name": name}


def _sheet_rename(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_calc_document()
    new_name = _require(params, "new_name")
    old_name = params.get("old_name")
    sheet = document.getSheets().getByName(old_name) if old_name else _active_sheet(document)
    sheet.Name = new_name
    return {}


def _sheet_switch(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_calc_document()
    name = _require(params, "name")
    sheets = document.getSheets()
    if not sheets.hasByName(name):
        raise OfficeCommandError(f"Листа '{name}' не существует")
    document.getCurrentController().setActiveSheet(sheets.getByName(name))
    return {}


ACTIONS: dict[str, Callable[[OfficeSession, dict[str, Any]], dict[str, Any]]] = {
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


def dispatch(session: OfficeSession, action: str, params: dict[str, Any]) -> dict[str, Any]:
    handler = ACTIONS.get(action)
    if handler is None:
        raise OfficeCommandError(f"Неизвестное действие: {action}")
    return handler(session, params) or {}
