"""UNO action handlers for the Jarvis <-> LibreOffice Writer bridge.

Every handler has the same signature — (session: OfficeSession, params: dict)
-> dict — and assumes a live UNO connection already exists (server.py calls
_ensure_desktop() before dispatching "open_document"; every other action
requires session.writer_document to already be set, enforced by
OfficeSession.require_writer_document()). ACTIONS is the dispatch table
server.py looks actions up in by name — keep this vocabulary in sync with
modules/office_writer/command_parser.py on the Jarvis backend side; the two
sides run in separate Python processes (system python3 with pyuno vs. the
backend's own venv) and can't share a literal import.
"""

from __future__ import annotations

import os
from typing import Any, Callable

import uno

from office_session import OfficeCommandError, OfficeSession, prop as _prop

# com.sun.star.text.ControlCharacter is a constants group (plain ints, not
# an enum) — hardcoded rather than dynamically imported, same reasoning as
# CharWeight/CharUnderline below: these are long-stable UNO API values.
_PARAGRAPH_BREAK = 0

_FILTER_BY_EXTENSION: dict[str, str] = {
    ".docx": "MS Word 2007 XML",
    ".doc": "MS Word 97",
    ".odt": "writer8",
    ".pdf": "writer_pdf_Export",
    ".txt": "Text",
    ".rtf": "Rich Text Format",
}

_PARA_ADJUST_BY_NAME: dict[str, str] = {
    "left": "LEFT",
    "right": "RIGHT",
    "center": "CENTER",
    "justify": "BLOCK",
}


def _require(params: dict[str, Any], key: str) -> Any:
    value = params.get(key)
    if value in (None, ""):
        raise OfficeCommandError(f"Не указан обязательный параметр '{key}'")
    return value


def _view_cursor(document: Any) -> Any:
    return document.getCurrentController().getViewCursor()


def _to_file_url(path: str) -> str:
    return uno.systemPathToFileUrl(os.path.abspath(os.path.expanduser(path)))


def _open_document(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    path = params.get("path")
    if path and os.path.exists(os.path.abspath(os.path.expanduser(path))):
        document = session.desktop.loadComponentFromURL(
            _to_file_url(path), "_blank", 0, (_prop("Hidden", False),)
        )
    else:
        # loadComponentFromURL on a path that doesn't exist yet either
        # raises or — verified empirically against a live LibreOffice 24.2,
        # see AGENT_NOTES.md — hangs indefinitely (presumably an interactive
        # "create this file?" prompt LibreOffice expects a human to click,
        # which never arrives here), wedging this handler's caller
        # (server.py holds one global lock across every action, so a stuck
        # call here blocks every other command too). Always create blank
        # instead and immediately give it the requested location via
        # storeAsURL, same pattern access_handlers.py's _open_database uses
        # for a brand-new database.
        document = session.desktop.loadComponentFromURL(
            "private:factory/swriter", "_blank", 0, (_prop("Hidden", False),)
        )
        if path:
            document.storeAsURL(_to_file_url(path), ())
    session.writer_document = document
    return {"opened": path or "новый документ"}


def _save_document(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_writer_document()
    path = params.get("path")
    if path:
        url = _to_file_url(path)
        filter_name = _FILTER_BY_EXTENSION.get(os.path.splitext(path)[1].lower(), "writer8")
        document.storeToURL(url, (_prop("FilterName", filter_name), _prop("Overwrite", True)))
    else:
        if not document.hasLocation():
            raise OfficeCommandError("У документа ещё нет пути на диске — укажи, куда сохранить.")
        document.store()
    return {}


def _close_document(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_writer_document()
    if params.get("save"):
        _save_document(session, {})
    document.close(False)
    session.writer_document = None
    return {}


def _undo(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    session.require_writer_document().getUndoManager().undo()
    return {}


def _redo(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    session.require_writer_document().getUndoManager().redo()
    return {}


def _insert_text(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_writer_document()
    content = _require(params, "content")
    position = params.get("position", "cursor")
    cursor = _view_cursor(document)
    if position == "end":
        cursor.gotoEnd(False)
    elif position == "start":
        cursor.gotoStart(False)
    text = document.getText()
    text.insertString(cursor, content, False)
    if position == "end":
        # "end" means "append a new chunk of text", the same intent as
        # pressing Enter after typing a paragraph in a word processor — so
        # a trailing paragraph break here (unlike the cursor/start variants,
        # genuine mid-document insertions where an uninvited break would be
        # wrong) leaves the cursor ready for whatever comes next. Verified
        # empirically this actually matters, not just tidiness: without it,
        # a follow-up insert_heading call re-styles this text's own
        # paragraph as a heading (ParaStyleName applies to "the paragraph
        # the cursor is in", not "a new one") and appends the heading text
        # into it instead of starting a fresh paragraph — see
        # modules/office_notes' notebook use case in AGENT_NOTES.md.
        text.insertControlCharacter(cursor, _PARAGRAPH_BREAK, False)
    return {}


def _replace_selection(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_writer_document()
    content = _require(params, "content")
    cursor = _view_cursor(document)
    # bAbsorb=True: consumes (replaces) whatever the cursor currently has
    # selected, rather than inserting alongside it.
    document.getText().insertString(cursor, content, True)
    return {}


def _delete_selection(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_writer_document()
    _view_cursor(document).setString("")
    return {}


def _set_format(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_writer_document()
    cursor = _view_cursor(document)
    if "bold" in params:
        # com.sun.star.awt.FontWeight is a constants group (plain floats,
        # not an enum): NORMAL=100.0, BOLD=150.0.
        cursor.CharWeight = 150.0 if params["bold"] else 100.0
    if "italic" in params:
        cursor.CharPosture = uno.Enum(
            "com.sun.star.awt.FontSlant", "ITALIC" if params["italic"] else "NONE"
        )
    if "underline" in params:
        # com.sun.star.awt.FontUnderline constants group: NONE=0, SINGLE=1.
        cursor.CharUnderline = 1 if params["underline"] else 0
    if "font_size" in params:
        cursor.CharHeight = float(params["font_size"])
    if "color" in params:
        cursor.CharColor = int(str(params["color"]).lstrip("#"), 16)
    if "align" in params:
        alignment = _PARA_ADJUST_BY_NAME.get(str(params["align"]).lower())
        if alignment is None:
            raise OfficeCommandError(f"Неизвестное выравнивание: {params['align']}")
        cursor.ParaAdjust = uno.Enum("com.sun.star.style.ParagraphAdjust", alignment)
    return {}


def _insert_heading(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_writer_document()
    content = _require(params, "text")
    level = int(params.get("level", 1))
    if not 1 <= level <= 10:
        raise OfficeCommandError("Уровень заголовка должен быть от 1 до 10")
    text = document.getText()
    cursor = _view_cursor(document)
    cursor.ParaStyleName = f"Heading {level}"
    text.insertString(cursor, content, False)
    text.insertControlCharacter(cursor, _PARAGRAPH_BREAK, False)
    cursor.ParaStyleName = "Default Paragraph Style"
    return {}


def _insert_list(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_writer_document()
    items = params.get("items")
    if not isinstance(items, list) or not items:
        raise OfficeCommandError("Нужен непустой список пунктов (items)")
    # "List Bullet"/"List Number" are the pre-7.x style names — current
    # LibreOffice (verified against 24.2) ships them as "List 1"/"Numbering 1"
    # instead; the old names raise a bare RuntimeException with no useful
    # message when assigned to ParaStyleName.
    style = "Numbering 1" if params.get("ordered") else "List 1"
    text = document.getText()
    cursor = _view_cursor(document)
    for item in items:
        cursor.ParaStyleName = style
        text.insertString(cursor, str(item), False)
        text.insertControlCharacter(cursor, _PARAGRAPH_BREAK, False)
    cursor.ParaStyleName = "Default Paragraph Style"
    return {}


def _list_headings(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    """Walks the document's paragraphs for anything styled "Heading N" —
    used by modules/office_notes' notebook/section/page voice UX (see
    AGENT_NOTES.md: OneNote has no LibreOffice analog, so Jarvis treats
    Writer's own heading hierarchy as a notebook's section/page structure)
    to read back the notebook's outline, but generic enough to double as a
    plain "what's the structure of this document" action for Writer itself."""
    document = session.require_writer_document()
    headings: list[dict[str, Any]] = []
    enumeration = document.getText().createEnumeration()
    while enumeration.hasMoreElements():
        paragraph = enumeration.nextElement()
        if not paragraph.supportsService("com.sun.star.text.Paragraph"):
            continue
        style_name = paragraph.ParaStyleName
        if not style_name.startswith("Heading "):
            continue
        try:
            level = int(style_name.removeprefix("Heading ").strip())
        except ValueError:
            continue
        headings.append({"level": level, "text": paragraph.getString()})
    return {"headings": headings}


def _insert_page_break(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_writer_document()
    text = document.getText()
    cursor = _view_cursor(document)
    text.insertControlCharacter(cursor, _PARAGRAPH_BREAK, False)
    cursor.BreakType = uno.Enum("com.sun.star.style.BreakType", "PAGE_BEFORE")
    return {}


def _insert_table(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_writer_document()
    rows = int(_require(params, "rows"))
    cols = int(_require(params, "cols"))
    if rows < 1 or cols < 1:
        raise OfficeCommandError("Число строк и столбцов должно быть не меньше 1")
    table = document.createInstance("com.sun.star.text.TextTable")
    table.initialize(rows, cols)
    document.getText().insertTextContent(_view_cursor(document), table, False)
    return {}


def _current_table_cell(document: Any) -> tuple[Any, str]:
    """Returns (table, cell_name) for the table the view cursor is
    currently positioned inside — the `TextTable`/`Cell` properties are only
    populated on a text cursor while it's inside a table cell."""
    cursor = _view_cursor(document)
    table = getattr(cursor, "TextTable", None)
    if table is None:
        raise OfficeCommandError("Курсор сейчас не внутри таблицы")
    return table, cursor.Cell.CellName


def _cell_indices(cell_name: str) -> tuple[int, int]:
    """Cell names are like "A1", "B12": letters=column (base-26, A=1),
    digits=row (1-based). Returns 0-based (row, col)."""
    letters = "".join(ch for ch in cell_name if ch.isalpha())
    digits = "".join(ch for ch in cell_name if ch.isdigit())
    col = 0
    for ch in letters:
        col = col * 26 + (ord(ch.upper()) - ord("A") + 1)
    return int(digits) - 1, col - 1


def _cell_name(row_index: int, col_index: int) -> str:
    col_index += 1
    letters = ""
    while col_index > 0:
        col_index, remainder = divmod(col_index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return f"{letters}{row_index + 1}"


def _reanchor_cursor_in_table(document: Any, table: Any, row_index: int, col_index: int) -> None:
    """Removing the row/column the cursor was in orphans the view cursor's
    range (verified empirically: cursor.TextTable comes back None right
    after such a removeByIndex, breaking any follow-up table command in the
    same voice session) — put it back in the nearest surviving cell of the
    same table, clamped to whatever rows/columns are left."""
    rows = table.getRows().Count
    cols = table.getColumns().Count
    if rows == 0 or cols == 0:
        return
    row_index = min(row_index, rows - 1)
    col_index = min(col_index, cols - 1)
    cell = table.getCellByName(_cell_name(row_index, col_index))
    document.getCurrentController().getViewCursor().gotoRange(cell.getStart(), False)


def _table_insert_row(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_writer_document()
    table, cell_name = _current_table_cell(document)
    row_index, _ = _cell_indices(cell_name)
    table.getRows().insertByIndex(row_index + 1, int(params.get("count", 1)))
    return {}


def _table_insert_column(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_writer_document()
    table, cell_name = _current_table_cell(document)
    _, col_index = _cell_indices(cell_name)
    table.getColumns().insertByIndex(col_index + 1, int(params.get("count", 1)))
    return {}


def _table_delete_row(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_writer_document()
    table, cell_name = _current_table_cell(document)
    row_index, col_index = _cell_indices(cell_name)
    table.getRows().removeByIndex(row_index, int(params.get("count", 1)))
    _reanchor_cursor_in_table(document, table, row_index, col_index)
    return {}


def _table_delete_column(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_writer_document()
    table, cell_name = _current_table_cell(document)
    row_index, col_index = _cell_indices(cell_name)
    table.getColumns().removeByIndex(col_index, int(params.get("count", 1)))
    _reanchor_cursor_in_table(document, table, row_index, col_index)
    return {}


ACTIONS: dict[str, Callable[[OfficeSession, dict[str, Any]], dict[str, Any]]] = {
    "open_document": _open_document,
    "save_document": _save_document,
    "close_document": _close_document,
    "undo": _undo,
    "redo": _redo,
    "insert_text": _insert_text,
    "replace_selection": _replace_selection,
    "delete_selection": _delete_selection,
    "set_format": _set_format,
    "insert_heading": _insert_heading,
    "list_headings": _list_headings,
    "insert_list": _insert_list,
    "insert_page_break": _insert_page_break,
    "insert_table": _insert_table,
    "table_insert_row": _table_insert_row,
    "table_insert_column": _table_insert_column,
    "table_delete_row": _table_delete_row,
    "table_delete_column": _table_delete_column,
}


def dispatch(session: OfficeSession, action: str, params: dict[str, Any]) -> dict[str, Any]:
    handler = ACTIONS.get(action)
    if handler is None:
        raise OfficeCommandError(f"Неизвестное действие: {action}")
    return handler(session, params) or {}
