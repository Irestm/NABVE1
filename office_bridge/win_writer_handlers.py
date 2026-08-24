"""win32com action handlers for the Windows Jarvis <-> Word bridge — the
Windows counterpart of office_bridge/writer_handlers.py.

Same ACTIONS vocabulary and params as the Linux/UNO side (kept in sync with
modules/office_writer/command_parser.py on the Jarvis backend, which is
identical on both OSes — see office_bridge/server_win.py's own docstring for
why the backend never needs to know which bridge answered it), reimplemented
against Word's COM object model instead of UNO. Constants below are cited
from the standard WdConstants/WdBuiltinStyle/WdUnits enumerations by name in
comments — hardcoded as literal ints rather than resolved through
win32com.client.gencache/constants, which needs a type-library cache
generated at least once and is one more thing that can silently be stale or
missing; these specific values are long-stable across Word versions, same
reasoning office_session.py gives for hardcoding UNO's own constants groups.

NOT exercised against a real Word install (no Windows in this dev
environment) — see office_bridge/server_win.py's module docstring.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from win_session import OfficeCommandError, WinOfficeSession, bgr_color

# WdUnits.wdStory
_WD_STORY = 6
# WdSaveOptions.wdDoNotSaveChanges
_WD_DO_NOT_SAVE_CHANGES = 0
# WdUnderline.wdUnderlineNone / wdUnderlineSingle
_WD_UNDERLINE_NONE = 0
_WD_UNDERLINE_SINGLE = 1
# WdParagraphAlignment: Left=0, Center=1, Right=2, Justify=3
_WD_ALIGN_BY_NAME: dict[str, int] = {"left": 0, "center": 1, "right": 2, "justify": 3}
# WdBuiltinStyle.wdStyleHeadingN = -(N + 1) for N in 1..9 — well-documented,
# stable range; Word only ships 9 built-in heading levels (unlike
# LibreOffice's 10), see AGENT_NOTES.md for that already-documented gap.
_WD_STYLE_NORMAL = -1
# WdInformation: wdWithInTable=12, wdStartOfRangeRowNumber=13,
# wdStartOfRangeColumnNumber=16.
_WD_WITH_IN_TABLE = 12
_WD_START_OF_RANGE_ROW = 13
_WD_START_OF_RANGE_COLUMN = 16


def _require(params: dict[str, Any], key: str) -> Any:
    value = params.get(key)
    if value in (None, ""):
        raise OfficeCommandError(f"Не указан обязательный параметр '{key}'")
    return value


def _abs_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _selection(session: WinOfficeSession) -> Any:
    session.require_word_document()
    return session.word_app.Selection


def _open_document(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    path = params.get("path")
    if path and os.path.exists(_abs_path(path)):
        document = session.word_app.Documents.Open(_abs_path(path))
    else:
        # Same reasoning as writer_handlers.py's _open_document: never call
        # Open() on a path that doesn't exist yet (Word's equivalent hang/
        # error-dialog risk isn't something to find out about live) — create
        # a blank document and, if a path was requested, save it there
        # immediately.
        document = session.word_app.Documents.Add()
        if path:
            document.SaveAs(_abs_path(path))
    session.word_document = document
    return {"opened": path or "новый документ"}


def _save_document(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_word_document()
    path = params.get("path")
    if path:
        # No explicit FileFormat map — Word's own SaveAs infers the format
        # from the extension in the given filename.
        document.SaveAs(_abs_path(path))
    else:
        if not document.Path:
            raise OfficeCommandError("У документа ещё нет пути на диске — укажи, куда сохранить.")
        document.Save()
    return {}


def _close_document(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_word_document()
    if params.get("save"):
        _save_document(session, {})
    document.Close(SaveChanges=_WD_DO_NOT_SAVE_CHANGES)
    session.word_document = None
    return {}


def _undo(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    session.require_word_document()
    session.word_app.Undo()
    return {}


def _redo(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    session.require_word_document()
    session.word_app.Redo()
    return {}


def _insert_text(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    selection = _selection(session)
    content = _require(params, "content")
    position = params.get("position", "cursor")
    if position == "end":
        selection.EndKey(Unit=_WD_STORY)
    elif position == "start":
        selection.HomeKey(Unit=_WD_STORY)
    else:
        # TypeText replaces a non-collapsed selection outright (Word's own
        # native behavior, exactly the semantics _replace_selection below
        # wants) — collapse first so a plain "insert at cursor" never eats
        # whatever text happened to be selected, matching UNO's bAbsorb=False.
        selection.Collapse()
    selection.TypeText(content)
    if position == "end":
        # See writer_handlers.py's _insert_text: "append" means "leave the
        # cursor ready for the next paragraph," so a follow-up insert_heading
        # doesn't re-style and merge into this same paragraph.
        selection.TypeParagraph()
    return {}


def _replace_selection(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    selection = _selection(session)
    content = _require(params, "content")
    selection.TypeText(content)
    return {}


def _delete_selection(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    _selection(session).Delete()
    return {}


def _set_format(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    selection = _selection(session)
    if "bold" in params:
        selection.Font.Bold = bool(params["bold"])
    if "italic" in params:
        selection.Font.Italic = bool(params["italic"])
    if "underline" in params:
        selection.Font.Underline = _WD_UNDERLINE_SINGLE if params["underline"] else _WD_UNDERLINE_NONE
    if "font_size" in params:
        selection.Font.Size = float(params["font_size"])
    if "color" in params:
        selection.Font.Color = bgr_color(params["color"])
    if "align" in params:
        alignment = _WD_ALIGN_BY_NAME.get(str(params["align"]).lower())
        if alignment is None:
            raise OfficeCommandError(f"Неизвестное выравнивание: {params['align']}")
        selection.ParagraphFormat.Alignment = alignment
    return {}


def _insert_heading(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    selection = _selection(session)
    content = _require(params, "text")
    level = int(params.get("level", 1))
    if not 1 <= level <= 9:
        raise OfficeCommandError("Уровень заголовка должен быть от 1 до 9")
    selection.Style = -(level + 1)  # wdStyleHeading{level}
    selection.TypeText(content)
    selection.TypeParagraph()
    selection.Style = _WD_STYLE_NORMAL
    return {}


def _insert_list(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    selection = _selection(session)
    items = params.get("items")
    if not isinstance(items, list) or not items:
        raise OfficeCommandError("Нужен непустой список пунктов (items)")
    # Unlike LibreOffice 24.2 (where these names crash — see
    # writer_handlers.py), "List Bullet"/"List Number" are Word's own
    # standard built-in style identifiers, used as-is. Assigned by name
    # (not a WdBuiltinStyle int, unlike headings above) since this specific
    # ID range isn't one this couldn't be independently verified for — on a
    # non-English-locale Word install this string may need to be the
    # localized style name instead; flagging rather than guessing further.
    style = "List Number" if params.get("ordered") else "List Bullet"
    for item in items:
        selection.Style = style
        selection.TypeText(str(item))
        selection.TypeParagraph()
    selection.Style = _WD_STYLE_NORMAL
    return {}


def _list_headings(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    """Same purpose as writer_handlers.py's _list_headings (modules/
    office_notes' notebook structure + generic "show document outline").
    Reads each heading level's own NameLocal from the style collection by
    WdBuiltinStyle id, rather than hardcoding the English "Heading N"
    string, so this still matches on a Word install running in a language
    other than English — the id->NameLocal mapping is language-agnostic,
    only the direct string comparison would not have been."""
    document = session.require_word_document()
    heading_style_names = {}
    for level in range(1, 10):
        try:
            heading_style_names[document.Styles(-(level + 1)).NameLocal] = level
        except Exception:
            continue

    headings: list[dict[str, Any]] = []
    for paragraph in document.Paragraphs:
        style_name = paragraph.Range.Style.NameLocal
        level = heading_style_names.get(style_name)
        if level is None:
            continue
        text = paragraph.Range.Text.rstrip("\r\x07")
        headings.append({"level": level, "text": text})
    return {"headings": headings}


def _insert_page_break(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    # WdBreakType.wdPageBreak = 7
    _selection(session).InsertBreak(Type=7)
    return {}


def _insert_table(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_word_document()
    rows = int(_require(params, "rows"))
    cols = int(_require(params, "cols"))
    if rows < 1 or cols < 1:
        raise OfficeCommandError("Число строк и столбцов должно быть не меньше 1")
    document.Tables.Add(Range=session.word_app.Selection.Range, NumRows=rows, NumColumns=cols)
    return {}


def _current_table_position(session: WinOfficeSession) -> tuple[Any, int, int]:
    """Returns (table, 0-based row, 0-based column) for the table the
    selection is currently inside — WdInformation.wdWithInTable/
    wdStartOfRangeRowNumber/wdStartOfRangeColumnNumber, standard VBA
    table-position introspection."""
    selection = _selection(session)
    if not selection.Information(_WD_WITH_IN_TABLE):
        raise OfficeCommandError("Курсор сейчас не внутри таблицы")
    row = selection.Information(_WD_START_OF_RANGE_ROW) - 1
    col = selection.Information(_WD_START_OF_RANGE_COLUMN) - 1
    return selection.Tables(1), row, col


def _reanchor_in_table(session: WinOfficeSession, table: Any, row: int, col: int) -> None:
    """Precautionary mirror of writer_handlers.py's own re-anchoring fix —
    Word's Selection is Range-based rather than UNO's cursor-in-a-disposed-
    cell object, so the specific "orphaned cursor" failure documented there
    may not even apply here, but moving back into a known-good cell after a
    row/column delete is cheap and can't make things worse either way."""
    rows = table.Rows.Count
    cols = table.Columns.Count
    if rows == 0 or cols == 0:
        return
    cell = table.Cell(min(row, rows - 1) + 1, min(col, cols - 1) + 1)
    cell.Range.Select()


def _table_insert_row(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    table, row, _ = _current_table_position(session)
    count = int(params.get("count", 1))
    insert_at = row + 2  # 1-based position right after the current row
    for _ in range(count):
        if insert_at <= table.Rows.Count:
            table.Rows.Add(BeforeRow=table.Rows(insert_at))
        else:
            table.Rows.Add()
        insert_at += 1
    return {}


def _table_insert_column(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    table, _, col = _current_table_position(session)
    count = int(params.get("count", 1))
    insert_at = col + 2
    for _ in range(count):
        if insert_at <= table.Columns.Count:
            table.Columns.Add(BeforeColumn=table.Columns(insert_at))
        else:
            table.Columns.Add()
        insert_at += 1
    return {}


def _table_delete_row(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    table, row, col = _current_table_position(session)
    count = int(params.get("count", 1))
    for _ in range(count):
        if table.Rows.Count == 0:
            break
        table.Rows(min(row, table.Rows.Count - 1) + 1).Delete()
    _reanchor_in_table(session, table, row, col)
    return {}


def _table_delete_column(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    table, row, col = _current_table_position(session)
    count = int(params.get("count", 1))
    for _ in range(count):
        if table.Columns.Count == 0:
            break
        table.Columns(min(col, table.Columns.Count - 1) + 1).Delete()
    _reanchor_in_table(session, table, row, col)
    return {}


ACTIONS: dict[str, Callable[[WinOfficeSession, dict[str, Any]], dict[str, Any]]] = {
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
