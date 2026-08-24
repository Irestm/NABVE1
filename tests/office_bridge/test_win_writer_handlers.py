from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import win_writer_handlers as handlers
from win_session import OfficeCommandError, WinOfficeSession


def _session_with_document() -> tuple[WinOfficeSession, MagicMock, MagicMock]:
    session = WinOfficeSession()
    word_app = MagicMock()
    document = MagicMock()
    document.Path = "/tmp/x.docx"
    session.word_app = word_app
    session.word_document = document
    return session, word_app, document


# --- open/save/close ---------------------------------------------------


def test_open_document_opens_existing_path(tmp_path) -> None:
    path = tmp_path / "existing.docx"
    path.write_text("x")
    session = WinOfficeSession()
    session.word_app = MagicMock()

    result = handlers.ACTIONS["open_document"](session, {"path": str(path)})

    session.word_app.Documents.Open.assert_called_once_with(str(path))
    session.word_app.Documents.Add.assert_not_called()
    assert result == {"opened": str(path)}
    assert session.word_document is session.word_app.Documents.Open.return_value


def test_open_document_creates_and_saves_when_path_does_not_exist(tmp_path) -> None:
    path = tmp_path / "new.docx"
    session = WinOfficeSession()
    session.word_app = MagicMock()

    handlers.ACTIONS["open_document"](session, {"path": str(path)})

    session.word_app.Documents.Open.assert_not_called()
    new_document = session.word_app.Documents.Add.return_value
    new_document.SaveAs.assert_called_once_with(str(path))
    assert session.word_document is new_document


def test_open_document_with_no_path_creates_blank_only() -> None:
    session = WinOfficeSession()
    session.word_app = MagicMock()

    result = handlers.ACTIONS["open_document"](session, {})

    new_document = session.word_app.Documents.Add.return_value
    new_document.SaveAs.assert_not_called()
    assert result == {"opened": "новый документ"}


def test_save_document_without_path_requires_existing_location() -> None:
    session, _, document = _session_with_document()
    document.Path = ""

    with pytest.raises(OfficeCommandError, match="ещё нет пути"):
        handlers.ACTIONS["save_document"](session, {})


def test_save_document_without_path_saves_in_place() -> None:
    session, _, document = _session_with_document()

    handlers.ACTIONS["save_document"](session, {})

    document.Save.assert_called_once()


def test_save_document_with_path_calls_save_as() -> None:
    session, _, document = _session_with_document()

    handlers.ACTIONS["save_document"](session, {"path": "/tmp/y.docx"})

    document.SaveAs.assert_called_once_with("/tmp/y.docx")


def test_close_document_saves_first_when_requested() -> None:
    session, _, document = _session_with_document()

    handlers.ACTIONS["close_document"](session, {"save": True})

    document.Save.assert_called_once()
    document.Close.assert_called_once_with(SaveChanges=0)
    assert session.word_document is None


def test_actions_requiring_a_document_raise_without_one() -> None:
    session = WinOfficeSession()
    with pytest.raises(OfficeCommandError, match="Нет открытого документа"):
        handlers.ACTIONS["insert_text"](session, {"content": "hi"})


# --- undo/redo -----------------------------------------------------------


def test_undo_calls_application_undo() -> None:
    session, word_app, _ = _session_with_document()
    handlers.ACTIONS["undo"](session, {})
    word_app.Undo.assert_called_once()


# --- insert_text / replace_selection / delete_selection ------------------


def test_insert_text_at_cursor_collapses_selection_first() -> None:
    session, word_app, _ = _session_with_document()
    selection = word_app.Selection

    handlers.ACTIONS["insert_text"](session, {"content": "привет"})

    selection.Collapse.assert_called_once_with()
    selection.TypeText.assert_called_once_with("привет")
    selection.TypeParagraph.assert_not_called()


def test_insert_text_at_end_appends_paragraph_break() -> None:
    session, word_app, _ = _session_with_document()
    selection = word_app.Selection

    handlers.ACTIONS["insert_text"](session, {"content": "привет", "position": "end"})

    selection.EndKey.assert_called_once_with(Unit=6)
    selection.TypeText.assert_called_once_with("привет")
    selection.TypeParagraph.assert_called_once()


def test_insert_text_at_start_moves_home_no_break() -> None:
    session, word_app, _ = _session_with_document()
    selection = word_app.Selection

    handlers.ACTIONS["insert_text"](session, {"content": "привет", "position": "start"})

    selection.HomeKey.assert_called_once_with(Unit=6)
    selection.TypeParagraph.assert_not_called()


def test_insert_text_requires_content() -> None:
    session, _, _ = _session_with_document()
    with pytest.raises(OfficeCommandError, match="content"):
        handlers.ACTIONS["insert_text"](session, {})


def test_replace_selection_never_collapses() -> None:
    session, word_app, _ = _session_with_document()
    handlers.ACTIONS["replace_selection"](session, {"content": "x"})
    word_app.Selection.Collapse.assert_not_called()
    word_app.Selection.TypeText.assert_called_once_with("x")


def test_delete_selection_calls_delete() -> None:
    session, word_app, _ = _session_with_document()
    handlers.ACTIONS["delete_selection"](session, {})
    word_app.Selection.Delete.assert_called_once()


# --- set_format ------------------------------------------------------------


def test_set_format_applies_only_given_properties() -> None:
    session, word_app, _ = _session_with_document()
    selection = word_app.Selection

    handlers.ACTIONS["set_format"](session, {"bold": True, "font_size": 14})

    assert selection.Font.Bold is True
    assert selection.Font.Size == 14.0


def test_set_format_color_is_converted_from_rgb_to_bgr() -> None:
    session, word_app, _ = _session_with_document()
    handlers.ACTIONS["set_format"](session, {"color": "#FF8000"})
    # #RRGGBB = FF8000 -> BGR packed = 0x0080FF
    assert word_app.Selection.Font.Color == 0x0080FF


def test_set_format_underline_toggles_between_word_constants() -> None:
    session, word_app, _ = _session_with_document()
    handlers.ACTIONS["set_format"](session, {"underline": True})
    assert word_app.Selection.Font.Underline == 1
    handlers.ACTIONS["set_format"](session, {"underline": False})
    assert word_app.Selection.Font.Underline == 0


def test_set_format_align_maps_known_values() -> None:
    session, word_app, _ = _session_with_document()
    handlers.ACTIONS["set_format"](session, {"align": "center"})
    assert word_app.Selection.ParagraphFormat.Alignment == 1


def test_set_format_unknown_align_raises() -> None:
    session, _, _ = _session_with_document()
    with pytest.raises(OfficeCommandError, match="выравнивание"):
        handlers.ACTIONS["set_format"](session, {"align": "diagonal"})


# --- insert_heading / insert_list / list_headings -------------------------


def test_insert_heading_rejects_out_of_range_level() -> None:
    session, _, _ = _session_with_document()
    with pytest.raises(OfficeCommandError, match="от 1 до 9"):
        handlers.ACTIONS["insert_heading"](session, {"text": "x", "level": 10})


def test_insert_heading_sets_style_then_resets_to_normal() -> None:
    session, word_app, _ = _session_with_document()
    selection = word_app.Selection

    handlers.ACTIONS["insert_heading"](session, {"text": "Заголовок", "level": 2})

    selection.TypeText.assert_called_once_with("Заголовок")
    selection.TypeParagraph.assert_called_once()
    # Style was assigned twice: -(2+1) then back to Normal (-1).
    assert selection.Style == -1  # final value after reset


def test_insert_list_requires_nonempty_items() -> None:
    session, _, _ = _session_with_document()
    with pytest.raises(OfficeCommandError, match="items"):
        handlers.ACTIONS["insert_list"](session, {"items": []})


def test_insert_list_ordered_uses_list_number_style() -> None:
    session, word_app, _ = _session_with_document()
    selection = word_app.Selection

    handlers.ACTIONS["insert_list"](session, {"items": ["a", "b"], "ordered": True})

    assert selection.TypeText.call_args_list == [(("a",), {}), (("b",), {})]
    assert selection.TypeParagraph.call_count == 2


def test_list_headings_reads_heading_style_names_from_document(monkeypatch) -> None:
    session, _, document = _session_with_document()

    def styles(style_id: int) -> MagicMock:
        style = MagicMock()
        level = -style_id - 1
        style.NameLocal = f"Heading {level}" if 1 <= level <= 9 else "?"
        return style

    document.Styles.side_effect = styles

    heading_paragraph = MagicMock()
    heading_paragraph.Range.Style.NameLocal = "Heading 2"
    heading_paragraph.Range.Text = "Заголовок\r"
    body_paragraph = MagicMock()
    body_paragraph.Range.Style.NameLocal = "Normal"
    document.Paragraphs = [heading_paragraph, body_paragraph]

    result = handlers.ACTIONS["list_headings"](session, {})

    assert result == {"headings": [{"level": 2, "text": "Заголовок"}]}


# --- tables -----------------------------------------------------------------


def test_insert_table_rejects_invalid_dimensions() -> None:
    session, _, _ = _session_with_document()
    with pytest.raises(OfficeCommandError, match="не меньше 1"):
        handlers.ACTIONS["insert_table"](session, {"rows": 0, "cols": 2})


def test_current_table_position_raises_outside_a_table() -> None:
    session, word_app, _ = _session_with_document()
    word_app.Selection.Information.return_value = False
    with pytest.raises(OfficeCommandError, match="не внутри таблицы"):
        handlers._current_table_position(session)


def test_current_table_position_reads_row_and_column() -> None:
    session, word_app, _ = _session_with_document()
    selection = word_app.Selection
    selection.Information.side_effect = lambda code: {12: True, 13: 3, 16: 2}[code]

    table, row, col = handlers._current_table_position(session)

    assert (row, col) == (2, 1)  # 0-based
    assert table is selection.Tables.return_value


def test_table_insert_row_appends_when_at_last_row() -> None:
    session, word_app, _ = _session_with_document()
    selection = word_app.Selection
    selection.Information.side_effect = lambda code: {12: True, 13: 3, 16: 1}[code]
    table = selection.Tables.return_value
    table.Rows.Count = 3

    handlers.ACTIONS["table_insert_row"](session, {})

    table.Rows.Add.assert_called_once_with()  # no BeforeRow — appended at end


def test_table_insert_row_inserts_before_the_next_row() -> None:
    session, word_app, _ = _session_with_document()
    selection = word_app.Selection
    selection.Information.side_effect = lambda code: {12: True, 13: 1, 16: 1}[code]
    table = selection.Tables.return_value
    table.Rows.Count = 5

    handlers.ACTIONS["table_insert_row"](session, {})

    table.Rows.assert_any_call(2)  # BeforeRow = row right after current (0-based row=0 -> 1-based 2)


def test_table_delete_row_deletes_requested_count() -> None:
    session, word_app, _ = _session_with_document()
    selection = word_app.Selection
    selection.Information.side_effect = lambda code: {12: True, 13: 1, 16: 1}[code]
    table = selection.Tables.return_value
    table.Rows.Count = 5
    table.Columns.Count = 2

    handlers.ACTIONS["table_delete_row"](session, {"count": 2})

    assert table.Rows.return_value.Delete.call_count == 2
