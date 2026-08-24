"""Shared UNO session state and small helpers for the Jarvis LibreOffice
bridge (office_bridge/server.py).

Split out from writer_handlers.py once calc_handlers.py needed the same
session type and PropertyValue helper — one soffice process (and one UNO
`desktop`) now serves every LibreOffice app Jarvis controls, matching how a
real LibreOffice session actually works (one window-manager-visible
instance, any number of open documents of different types), rather than a
separate soffice process per app.
"""

from __future__ import annotations

from typing import Any

from com.sun.star.beans import PropertyValue


class OfficeCommandError(Exception):
    """Raised by a handler for a caller mistake (no document/spreadsheet
    open, cursor not in a table, unknown alignment, missing required
    param, ...). office_bridge/server.py catches this (and any other
    exception — a raw UNO/IDL exception type from a failed API call) and
    turns it into a {"status": "error"} reply; handlers themselves never
    touch the wire format."""


class OfficeSession:
    """Per-process "what's connected/open" state — this bridge only ever
    serves one Jarvis backend at a time (see
    modules/office_writer/bridge_client.py and
    modules/office_excel/bridge_client.py), so a plain instance held by
    server.py is enough; no per-request or per-user scoping needed.
    `desktop` is shared across every app (one UNO connection); each app
    gets its own document slot since a user can plausibly have a Writer
    document and a Calc spreadsheet open through Jarvis at the same time."""

    def __init__(self) -> None:
        # The raw component context, alongside `desktop` — access_handlers.py
        # needs it directly to create a fresh com.sun.star.sdb.DatabaseContext
        # service (ctx.ServiceManager.createInstanceWithContext(...)) when
        # creating a brand-new database; `desktop` alone doesn't expose a
        # general service-creation entry point.
        self.ctx: Any = None
        self.desktop: Any = None
        self.writer_document: Any = None
        self.calc_document: Any = None
        self.impress_document: Any = None
        self.access_document: Any = None
        # Unlike the other three apps, Base's SQL connection is a distinct
        # object from the document itself (com.sun.star.sdbc.XConnection,
        # obtained once via access_document.DataSource.getConnection() —
        # see access_handlers.py's _open_database) and is what every SQL
        # action actually runs against, so it's cached here rather than
        # re-fetched per action: re-deriving a fresh connection from a
        # database document that was CREATED in-process (dbContext.
        # createInstance(), not opened from an existing file) intermittently
        # loses track of the embedded HSQLDB driver and fails with "driver
        # class could not be loaded" — verified empirically against a live
        # LibreOffice 24.2, see AGENT_NOTES.md.
        self.access_connection: Any = None

    def require_writer_document(self) -> Any:
        if self.writer_document is None:
            raise OfficeCommandError("Нет открытого документа Writer — сначала открой документ.")
        return self.writer_document

    def require_calc_document(self) -> Any:
        if self.calc_document is None:
            raise OfficeCommandError("Нет открытой таблицы Calc — сначала открой таблицу.")
        return self.calc_document

    def require_impress_document(self) -> Any:
        if self.impress_document is None:
            raise OfficeCommandError("Нет открытой презентации Impress — сначала открой презентацию.")
        return self.impress_document

    def require_access_connection(self) -> Any:
        if self.access_connection is None:
            raise OfficeCommandError("Нет открытой базы данных — сначала открой базу.")
        return self.access_connection


def prop(name: str, value: Any) -> PropertyValue:
    property_value = PropertyValue()
    property_value.Name = name
    property_value.Value = value
    return property_value
