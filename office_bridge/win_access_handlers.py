"""win32com action handlers for the Windows Jarvis <-> Access bridge — the
Windows counterpart of office_bridge/access_handlers.py.

Unlike the Linux/UNO side (LibreOffice Base, .odb + embedded HSQLDB — no
reliable writer for real Microsoft formats), Windows has genuine MS Access
available via COM: session.access_app is a visible Access.Application
instance (same always-visible live-editing premise as Word/Excel/PowerPoint
here), opening/creating a real .accdb file. Every SQL action runs against
`access_app.CurrentDb()` (a DAO Database object, cached in
session.access_connection despite the name — kept for symmetry with
WinOfficeSession.require_access_connection()) rather than a second, separate
ADO connection to the same file, avoiding any risk of two different
connections independently locking the same .accdb.

DDL (CREATE/DROP TABLE) still builds SQL with quoted/validated identifiers,
same as access_handlers.py — identifiers aren't parameterizable in any SQL
dialect, and these names come from structured voice-parsed params, not raw
passthrough SQL (see access_handlers.py's own docstring on that threat
model). Row VALUES, unlike the Linux side, go through a real parameterized
DAO QueryDef instead of hand-quoted SQL literals — a genuine improvement
this app's COM access allows, not just a port.

Not exercised against a real Access install — see
office_bridge/server_win.py's module docstring.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from win_session import OfficeCommandError, WinOfficeSession

# Access/DAO column types, keyed by the same small vocabulary
# modules/office_access/command_parser.py already maps Russian words onto
# (see access_handlers.py's own _COLUMN_TYPE_SQL for the Linux/HSQLDB
# equivalent) — Access SQL's own DDL type names, close enough to ANSI SQL
# that these differ from HSQLDB's mostly just in spelling.
_COLUMN_TYPE_SQL: dict[str, str] = {
    "text": "TEXT(255)",
    "number": "INTEGER",
    "decimal": "DOUBLE",
    "date": "DATETIME",
    "boolean": "YESNO",
}


def _require(params: dict[str, Any], key: str) -> Any:
    value = params.get(key)
    if value in (None, ""):
        raise OfficeCommandError(f"Не указан обязательный параметр '{key}'")
    return value


def _abs_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _quote_identifier(name: str) -> str:
    # Access SQL bracket-quotes identifiers rather than double-quoting them.
    if "]" in name:
        raise OfficeCommandError(f"Недопустимое имя: {name}")
    return f"[{name}]"


def _open_database(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    path = str(_require(params, "path"))
    abs_path = _abs_path(path)
    if os.path.exists(abs_path):
        session.access_app.OpenCurrentDatabase(abs_path)
    else:
        # NewCurrentDatabase creates a brand-new empty .accdb at this exact
        # path and opens it — unlike Documents.Open/Workbooks.Open on the
        # other three apps, there's no "don't call Open on a path that
        # doesn't exist yet" workaround needed here, since this IS the
        # correct call for the "doesn't exist yet" case.
        session.access_app.NewCurrentDatabase(abs_path)
    session.access_connection = session.access_app.CurrentDb()
    return {"opened": path}


def _save_database(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    session.require_access_connection()
    # Access auto-persists DDL/DML as each statement runs (no separate
    # "unsaved changes" document state the way Word/Excel/PowerPoint have) —
    # nothing to explicitly flush here beyond confirming a database is open.
    return {}


def _close_database(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    session.require_access_connection()
    session.access_app.CloseCurrentDatabase()
    session.access_connection = None
    return {}


def _create_table(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    database = session.require_access_connection()
    name = str(_require(params, "name"))
    columns = params.get("columns")
    if not isinstance(columns, list) or not columns:
        raise OfficeCommandError("Нужен непустой список колонок (columns)")

    column_defs = []
    for column in columns:
        column_name = column.get("name") if isinstance(column, dict) else None
        column_type = _COLUMN_TYPE_SQL.get(str(column.get("type", "text")).lower()) if isinstance(column, dict) else None
        if not column_name or column_type is None:
            raise OfficeCommandError(f"Некорректное описание колонки: {column}")
        column_defs.append(f"{_quote_identifier(column_name)} {column_type}")

    ddl = (
        f"CREATE TABLE {_quote_identifier(name)} "
        f"(ID AUTOINCREMENT PRIMARY KEY, {', '.join(column_defs)})"
    )
    database.Execute(ddl)
    return {}


def _delete_table(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    database = session.require_access_connection()
    name = str(_require(params, "name"))
    database.Execute(f"DROP TABLE {_quote_identifier(name)}")
    return {}


def _list_tables(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    database = session.require_access_connection()
    # MSysObjects Type=1 is a plain user table, Flags=0 excludes system
    # tables that also carry Type=1 — the standard DAO way to enumerate
    # user-created tables only.
    names = []
    for table_def in database.TableDefs:
        if not table_def.Name.startswith("MSys") and not table_def.Name.startswith("~"):
            names.append(table_def.Name)
    return {"tables": names}


def _execute_parameterized(database: Any, sql: str, values: list[Any]) -> None:
    """Runs `sql` (with `?` positional placeholders) as a real bound DAO
    parameter query — a genuine improvement over access_handlers.py's
    hand-quoted SQL literals for row values, made possible by having real
    DAO available here. `""` as the QueryDef name makes it temporary/
    unnamed — standard DAO idiom for a one-off parameterized statement."""
    query_def = database.CreateQueryDef("", sql)
    try:
        for index, value in enumerate(values):
            query_def.Parameters(index).Value = value
        query_def.Execute()
    finally:
        query_def.Close()


def _insert_row(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    database = session.require_access_connection()
    table = str(_require(params, "table"))
    values = params.get("values")
    if not isinstance(values, dict) or not values:
        raise OfficeCommandError("Нужен непустой набор значений (values)")

    columns_sql = ", ".join(_quote_identifier(key) for key in values)
    placeholders = ", ".join("?" for _ in values)
    _execute_parameterized(
        database,
        f"INSERT INTO {_quote_identifier(table)} ({columns_sql}) VALUES ({placeholders})",
        list(values.values()),
    )
    return {}


def _update_rows(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    database = session.require_access_connection()
    table = str(_require(params, "table"))
    set_values = params.get("set")
    if not isinstance(set_values, dict) or not set_values:
        raise OfficeCommandError("Нужен непустой набор новых значений (set)")
    where_column = str(_require(params, "where_column"))
    where_value = _require(params, "where_value")

    assignments = ", ".join(f"{_quote_identifier(k)} = ?" for k in set_values)
    _execute_parameterized(
        database,
        f"UPDATE {_quote_identifier(table)} SET {assignments} WHERE {_quote_identifier(where_column)} = ?",
        [*set_values.values(), where_value],
    )
    return {}


def _delete_rows(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    database = session.require_access_connection()
    table = str(_require(params, "table"))
    where_column = str(_require(params, "where_column"))
    where_value = _require(params, "where_value")

    _execute_parameterized(
        database,
        f"DELETE FROM {_quote_identifier(table)} WHERE {_quote_identifier(where_column)} = ?",
        [where_value],
    )
    return {}


def _list_rows(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    database = session.require_access_connection()
    table = str(_require(params, "table"))
    limit = int(params.get("limit", 10))

    recordset = database.OpenRecordset(f"SELECT TOP {limit} * FROM {_quote_identifier(table)}")
    column_names = [field.Name for field in recordset.Fields]
    rows: list[dict[str, Any]] = []
    while not recordset.EOF:
        rows.append(
            {name: ("" if field.Value is None else str(field.Value)) for name, field in zip(column_names, recordset.Fields)}
        )
        recordset.MoveNext()
    recordset.Close()
    return {"columns": column_names, "rows": rows}


ACTIONS: dict[str, Callable[[WinOfficeSession, dict[str, Any]], dict[str, Any]]] = {
    "open_database": _open_database,
    "save_database": _save_database,
    "close_database": _close_database,
    "create_table": _create_table,
    "delete_table": _delete_table,
    "list_tables": _list_tables,
    "insert_row": _insert_row,
    "update_rows": _update_rows,
    "delete_rows": _delete_rows,
    "list_rows": _list_rows,
}
