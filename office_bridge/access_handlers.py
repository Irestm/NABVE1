"""UNO action handlers for the Jarvis <-> LibreOffice Base bridge.

Same shape as writer_handlers.py/calc_handlers.py/impress_handlers.py —
(session: OfficeSession, params: dict) -> dict. "Access" here really means
LibreOffice Base's own native format (an .odb container around an embedded
HSQLDB database) — LibreOffice has no reliable writer for Microsoft's
.accdb/.mdb formats, so opening/saving always uses .odb regardless of what
extension a caller's `path` happens to have. Documented as a deliberate
scope decision, not an oversight — see AGENT_NOTES.md.

Structurally different from the other three apps in one way: every action
here runs against session.access_connection (a com.sun.star.sdbc.XConnection,
SQL-flavored — createStatement()/executeQuery()/execute()), not the
document object itself. Empirically verified against a live LibreOffice
24.2 (see AGENT_NOTES.md): a brand-new database has no working connection
until its document has been stored to a real file location at least once
("No storage or URL was given" otherwise) — so, unlike Writer/Calc/Impress,
open_database always requires an explicit `path` rather than supporting a
blank/unsaved session.
"""

from __future__ import annotations

import os
from typing import Any, Callable

import uno

from office_session import OfficeCommandError, OfficeSession, prop as _prop

# HSQLDB (LibreOffice Base's embedded engine) column types, keyed by the
# small English vocabulary this module's own command_parser.py maps Russian
# column-type words onto (see modules/office_access/command_parser.py) —
# deliberately small (text/number/decimal/date/boolean) rather than
# exposing HSQLDB's full type system, matching this app's "не
# переусложнять" convention for every other office module's own small
# lookup tables (colors, alignments, ...).
_COLUMN_TYPE_SQL: dict[str, str] = {
    "text": "VARCHAR(255)",
    "number": "INTEGER",
    "decimal": "DOUBLE",
    "date": "DATE",
    "boolean": "BOOLEAN",
}


def _require(params: dict[str, Any], key: str) -> Any:
    value = params.get(key)
    if value in (None, ""):
        raise OfficeCommandError(f"Не указан обязательный параметр '{key}'")
    return value


def _to_file_url(path: str) -> str:
    return uno.systemPathToFileUrl(os.path.abspath(os.path.expanduser(path)))


def _quote_identifier(name: str) -> str:
    # HSQLDB (like most SQL dialects) rejects identifiers containing a
    # literal double-quote outright were they ever to appear here — table/
    # column names come from voice-parsed params, not raw user SQL, so this
    # is a defensive check against a malformed name, not an injection
    # concern the caller needs to reason about.
    if '"' in name:
        raise OfficeCommandError(f"Недопустимое имя: {name}")
    return f'"{name}"'


def _open_database(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    path = str(_require(params, "path"))
    abs_path = os.path.abspath(os.path.expanduser(path))

    if os.path.exists(abs_path):
        document = session.desktop.loadComponentFromURL(
            _to_file_url(abs_path), "_blank", 0, (_prop("Hidden", False),)
        )
        connection = document.DataSource.getConnection("", "")
    else:
        db_context = session.ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.sdb.DatabaseContext", session.ctx
        )
        data_source = db_context.createInstance()
        data_source.URL = "sdbc:embedded:hsqldb"
        document = data_source.DatabaseDocument
        document.storeAsURL(_to_file_url(abs_path), ())
        connection = data_source.getConnection("", "")

    session.access_document = document
    session.access_connection = connection
    return {"opened": path}


def _save_database(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.access_document
    if document is None:
        raise OfficeCommandError("Нет открытой базы данных — сначала открой базу.")
    document.store()
    return {}


def _close_database(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.access_document
    if document is None:
        raise OfficeCommandError("Нет открытой базы данных — сначала открой базу.")
    if params.get("save"):
        document.store()
    document.close(False)
    session.access_document = None
    session.access_connection = None
    return {}


def _create_table(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    connection = session.require_access_connection()
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
        f"(ID INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, {', '.join(column_defs)})"
    )
    connection.createStatement().execute(ddl)
    connection.getTables().refresh()
    return {}


def _delete_table(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    connection = session.require_access_connection()
    name = str(_require(params, "name"))
    connection.createStatement().execute(f"DROP TABLE {_quote_identifier(name)}")
    connection.getTables().refresh()
    return {}


def _list_tables(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    connection = session.require_access_connection()
    tables = connection.getTables()
    tables.refresh()
    names = []
    enumeration = tables.createEnumeration()
    while enumeration.hasMoreElements():
        names.append(enumeration.nextElement().Name)
    return {"tables": names}


def _sql_literal(value: Any) -> str:
    """Renders one Python value as a literal for a hand-built SQL
    statement — this module never accepts raw SQL from a caller (see this
    file's own docstring: params are structured, not a passthrough query
    action), so the only injection surface is a value containing a single
    quote, handled by doubling it (the standard SQL-92 escape)."""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def _insert_row(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    connection = session.require_access_connection()
    table = str(_require(params, "table"))
    values = params.get("values")
    if not isinstance(values, dict) or not values:
        raise OfficeCommandError("Нужен непустой набор значений (values)")

    columns_sql = ", ".join(_quote_identifier(key) for key in values)
    values_sql = ", ".join(_sql_literal(value) for value in values.values())
    connection.createStatement().execute(
        f"INSERT INTO {_quote_identifier(table)} ({columns_sql}) VALUES ({values_sql})"
    )
    return {}


def _update_rows(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    connection = session.require_access_connection()
    table = str(_require(params, "table"))
    set_values = params.get("set")
    if not isinstance(set_values, dict) or not set_values:
        raise OfficeCommandError("Нужен непустой набор новых значений (set)")
    where_column = str(_require(params, "where_column"))
    where_value = _require(params, "where_value")

    assignments = ", ".join(f"{_quote_identifier(k)} = {_sql_literal(v)}" for k, v in set_values.items())
    connection.createStatement().execute(
        f"UPDATE {_quote_identifier(table)} SET {assignments} "
        f"WHERE {_quote_identifier(where_column)} = {_sql_literal(where_value)}"
    )
    return {}


def _delete_rows(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    connection = session.require_access_connection()
    table = str(_require(params, "table"))
    where_column = str(_require(params, "where_column"))
    where_value = _require(params, "where_value")

    connection.createStatement().execute(
        f"DELETE FROM {_quote_identifier(table)} "
        f"WHERE {_quote_identifier(where_column)} = {_sql_literal(where_value)}"
    )
    return {}


def _list_rows(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    connection = session.require_access_connection()
    table = str(_require(params, "table"))
    limit = int(params.get("limit", 10))

    statement = connection.createStatement()
    result_set = statement.executeQuery(f"SELECT * FROM {_quote_identifier(table)}")
    metadata = result_set.MetaData
    column_count = metadata.ColumnCount
    column_names = [metadata.getColumnName(i + 1) for i in range(column_count)]

    rows: list[dict[str, Any]] = []
    while result_set.next() and len(rows) < limit:
        rows.append({name: result_set.getString(index + 1) for index, name in enumerate(column_names)})
    return {"columns": column_names, "rows": rows}


ACTIONS: dict[str, Callable[[OfficeSession, dict[str, Any]], dict[str, Any]]] = {
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


def dispatch(session: OfficeSession, action: str, params: dict[str, Any]) -> dict[str, Any]:
    handler = ACTIONS.get(action)
    if handler is None:
        raise OfficeCommandError(f"Неизвестное действие: {action}")
    return handler(session, params) or {}
