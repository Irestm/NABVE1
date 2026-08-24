from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import win_access_handlers as handlers
from win_session import OfficeCommandError, WinOfficeSession


def _session_with_database() -> tuple[WinOfficeSession, MagicMock, MagicMock]:
    session = WinOfficeSession()
    access_app = MagicMock()
    database = MagicMock()
    session.access_app = access_app
    session.access_connection = database
    return session, access_app, database


def test_open_database_requires_path() -> None:
    session = WinOfficeSession()
    session.access_app = MagicMock()
    with pytest.raises(OfficeCommandError, match="path"):
        handlers.ACTIONS["open_database"](session, {})


def test_open_database_opens_existing_file(tmp_path) -> None:
    path = tmp_path / "existing.accdb"
    path.write_text("x")
    session = WinOfficeSession()
    session.access_app = MagicMock()

    handlers.ACTIONS["open_database"](session, {"path": str(path)})

    session.access_app.OpenCurrentDatabase.assert_called_once_with(str(path))
    session.access_app.NewCurrentDatabase.assert_not_called()
    assert session.access_connection is session.access_app.CurrentDb.return_value


def test_open_database_creates_new_file_when_missing(tmp_path) -> None:
    path = tmp_path / "new.accdb"
    session = WinOfficeSession()
    session.access_app = MagicMock()

    handlers.ACTIONS["open_database"](session, {"path": str(path)})

    session.access_app.NewCurrentDatabase.assert_called_once_with(str(path))
    session.access_app.OpenCurrentDatabase.assert_not_called()


def test_close_database_calls_close_current_database() -> None:
    session, access_app, _ = _session_with_database()
    handlers.ACTIONS["close_database"](session, {})
    access_app.CloseCurrentDatabase.assert_called_once()
    assert session.access_connection is None


def test_actions_requiring_a_database_raise_without_one() -> None:
    session = WinOfficeSession()
    with pytest.raises(OfficeCommandError, match="Нет открытой базы"):
        handlers.ACTIONS["list_tables"](session, {})


# --- create_table / delete_table / list_tables ------------------------


def test_create_table_rejects_empty_columns() -> None:
    session, _, _ = _session_with_database()
    with pytest.raises(OfficeCommandError, match="колонок"):
        handlers.ACTIONS["create_table"](session, {"name": "t", "columns": []})


def test_create_table_rejects_unknown_column_type() -> None:
    session, _, _ = _session_with_database()
    with pytest.raises(OfficeCommandError, match="колонк"):
        handlers.ACTIONS["create_table"](session, {"name": "t", "columns": [{"name": "x", "type": "blob"}]})


def test_create_table_builds_ddl_with_autoincrement_id() -> None:
    session, _, database = _session_with_database()

    handlers.ACTIONS["create_table"](
        session, {"name": "Люди", "columns": [{"name": "Имя", "type": "text"}, {"name": "Возраст", "type": "number"}]}
    )

    ddl = database.Execute.call_args[0][0]
    assert ddl.startswith("CREATE TABLE [Люди] (ID AUTOINCREMENT PRIMARY KEY")
    assert "[Имя] TEXT(255)" in ddl
    assert "[Возраст] INTEGER" in ddl


def test_quote_identifier_rejects_embedded_bracket() -> None:
    with pytest.raises(OfficeCommandError):
        handlers._quote_identifier("na]me")


def test_list_tables_excludes_system_and_hidden_tables() -> None:
    session, _, database = _session_with_database()
    user_table = MagicMock(Name="Люди")
    system_table = MagicMock(Name="MSysObjects")
    hidden_table = MagicMock(Name="~TMPClp")
    database.TableDefs = [user_table, system_table, hidden_table]

    result = handlers.ACTIONS["list_tables"](session, {})

    assert result == {"tables": ["Люди"]}


# --- insert_row / update_rows / delete_rows — real DAO parameter binding ---


def _indexed_parameters(query_def: MagicMock) -> dict[int, MagicMock]:
    """DAO's QueryDef.Parameters(i) returns a distinct Parameter object per
    index — MagicMock's default return_value would collapse every index
    into the SAME mock (masking a bug where a later parameter silently
    overwrites an earlier one), so this configures one mock per index."""
    by_index: dict[int, MagicMock] = {}
    query_def.Parameters.side_effect = lambda i: by_index.setdefault(i, MagicMock())
    return by_index


def test_insert_row_uses_a_parameterized_query_def() -> None:
    session, _, database = _session_with_database()
    query_def = database.CreateQueryDef.return_value
    parameters = _indexed_parameters(query_def)

    handlers.ACTIONS["insert_row"](session, {"table": "Люди", "values": {"Имя": "Иван", "Возраст": 31}})

    sql = database.CreateQueryDef.call_args[0][1]
    assert sql == "INSERT INTO [Люди] ([Имя], [Возраст]) VALUES (?, ?)"
    assert parameters[0].Value == "Иван"
    assert parameters[1].Value == 31
    query_def.Execute.assert_called_once()
    query_def.Close.assert_called_once()


def test_insert_row_closes_query_def_even_on_failure() -> None:
    session, _, database = _session_with_database()
    query_def = database.CreateQueryDef.return_value
    query_def.Execute.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        handlers.ACTIONS["insert_row"](session, {"table": "t", "values": {"a": 1}})

    query_def.Close.assert_called_once()


def test_insert_row_requires_nonempty_values() -> None:
    session, _, _ = _session_with_database()
    with pytest.raises(OfficeCommandError, match="значений"):
        handlers.ACTIONS["insert_row"](session, {"table": "t", "values": {}})


def test_update_rows_places_where_value_parameter_last() -> None:
    session, _, database = _session_with_database()
    query_def = database.CreateQueryDef.return_value
    parameters = _indexed_parameters(query_def)

    handlers.ACTIONS["update_rows"](
        session, {"table": "t", "set": {"a": "x"}, "where_column": "id", "where_value": 5}
    )

    sql = database.CreateQueryDef.call_args[0][1]
    assert sql == "UPDATE [t] SET [a] = ? WHERE [id] = ?"
    assert parameters[0].Value == "x"
    assert parameters[1].Value == 5


def test_delete_rows_single_equality_where() -> None:
    session, _, database = _session_with_database()

    handlers.ACTIONS["delete_rows"](session, {"table": "t", "where_column": "id", "where_value": 5})

    sql = database.CreateQueryDef.call_args[0][1]
    assert sql == "DELETE FROM [t] WHERE [id] = ?"


# --- list_rows ------------------------------------------------------------


def test_list_rows_uses_top_n_and_stringifies_values() -> None:
    session, _, database = _session_with_database()
    recordset = database.OpenRecordset.return_value
    field_a = MagicMock(Name="id", Value=1)
    field_b = MagicMock(Name="name", Value=None)
    recordset.Fields = [field_a, field_b]
    recordset.EOF = False

    def move_next() -> None:
        recordset.EOF = True

    recordset.MoveNext.side_effect = move_next

    result = handlers.ACTIONS["list_rows"](session, {"table": "t", "limit": 5})

    database.OpenRecordset.assert_called_once_with("SELECT TOP 5 * FROM [t]")
    assert result == {"columns": ["id", "name"], "rows": [{"id": "1", "name": ""}]}
    recordset.Close.assert_called_once()
