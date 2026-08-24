"""Shared win32com session state for the Windows Jarvis Office bridge
(office_bridge/server_win.py) — the Windows counterpart of
office_bridge/office_session.py.

Deliberately does NOT import anything from office_session.py: that module
imports `com.sun.star.beans.PropertyValue` at module level (UNO), which
isn't installed on Windows and would defeat the entire point of this bridge
not depending on pyuno — see requirements.txt's pywin32 entry. OfficeCommandError
is therefore its own two-line class here rather than shared with the Linux
side, even though the two happen to be identical in shape."""

from __future__ import annotations

from typing import Any

__all__ = ["OfficeCommandError", "WinOfficeSession", "bgr_color"]


class OfficeCommandError(Exception):
    """Raised by a handler for a caller mistake (no document/workbook/
    presentation/database open, cursor not in a table, unknown alignment,
    missing required param, ...). office_bridge/server_win.py catches this
    (and any other exception — a raw COM error from a failed automation
    call) and turns it into a {"status": "error"} reply; handlers themselves
    never touch the wire format."""


def bgr_color(hex_value: str) -> int:
    """Word/Excel/PowerPoint's Font.Color (and Excel's Interior.Color) all
    take a BGR-packed long (0xBBGGRR) — the opposite byte order from the
    #RRGGBB hex strings this bridge's params accept everywhere else (same
    convention the Linux/UNO side's CharColor already uses) — shared here
    since win_writer_handlers.py/win_calc_handlers.py/win_impress_handlers.py
    all need the identical conversion."""
    rgb = int(str(hex_value).lstrip("#"), 16)
    r, g, b = (rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF
    return (b << 16) | (g << 8) | r


class WinOfficeSession:
    """Per-process "what's connected/open" state — same one-bridge-per-
    machine assumption as OfficeSession (see that module's docstring): one
    Word/Excel/PowerPoint/Access Application instance each, kept alive and
    visible across commands for the live-editing UX. Application objects are
    late-bound win32com.client.Dispatch results (Any) rather than typed —
    same reasoning office_session.py gives for its own UNO `Any` fields."""

    def __init__(self) -> None:
        self.word_app: Any = None
        self.excel_app: Any = None
        self.powerpoint_app: Any = None
        self.word_document: Any = None
        self.excel_workbook: Any = None
        self.powerpoint_presentation: Any = None
        # Real MS Access via COM automation (not embedded HSQLDB like the
        # Linux/.odb side) — access_app is the visible Access.Application
        # instance itself (open/create/close a database through it, same
        # always-visible pattern as the other three apps);
        # access_connection holds access_app.CurrentDb() (a DAO Database,
        # despite the generic field name kept for symmetry with
        # require_access_connection() below) — every SQL action in
        # win_access_handlers.py runs against this, not a second/separate
        # ADO connection to the same file.
        self.access_app: Any = None
        self.access_connection: Any = None

    def require_word_document(self) -> Any:
        if self.word_document is None:
            raise OfficeCommandError("Нет открытого документа Word — сначала открой документ.")
        return self.word_document

    def require_excel_workbook(self) -> Any:
        if self.excel_workbook is None:
            raise OfficeCommandError("Нет открытой книги Excel — сначала открой таблицу.")
        return self.excel_workbook

    def require_powerpoint_presentation(self) -> Any:
        if self.powerpoint_presentation is None:
            raise OfficeCommandError("Нет открытой презентации PowerPoint — сначала открой презентацию.")
        return self.powerpoint_presentation

    def require_access_connection(self) -> Any:
        if self.access_connection is None:
            raise OfficeCommandError("Нет открытой базы данных — сначала открой базу.")
        return self.access_connection
