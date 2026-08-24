from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import win_impress_handlers as handlers
from win_session import OfficeCommandError, WinOfficeSession


def _session_with_presentation() -> tuple[WinOfficeSession, MagicMock, MagicMock]:
    session = WinOfficeSession()
    powerpoint_app = MagicMock()
    presentation = MagicMock()
    presentation.Path = "/tmp/x.pptx"
    presentation.Application = powerpoint_app
    session.powerpoint_app = powerpoint_app
    session.powerpoint_presentation = presentation
    return session, powerpoint_app, presentation


def test_open_presentation_opens_existing_path(tmp_path) -> None:
    path = tmp_path / "existing.pptx"
    path.write_text("x")
    session = WinOfficeSession()
    session.powerpoint_app = MagicMock()

    handlers.ACTIONS["open_presentation"](session, {"path": str(path)})

    session.powerpoint_app.Presentations.Open.assert_called_once_with(str(path))


def test_open_presentation_creates_and_saves_when_missing(tmp_path) -> None:
    path = tmp_path / "new.pptx"
    session = WinOfficeSession()
    session.powerpoint_app = MagicMock()

    handlers.ACTIONS["open_presentation"](session, {"path": str(path)})

    new_presentation = session.powerpoint_app.Presentations.Add.return_value
    new_presentation.SaveAs.assert_called_once_with(str(path))


def test_save_presentation_without_path_requires_existing_location() -> None:
    session, _, presentation = _session_with_presentation()
    presentation.Path = ""
    with pytest.raises(OfficeCommandError, match="ещё нет пути"):
        handlers.ACTIONS["save_presentation"](session, {})


def test_close_presentation_saves_first_when_requested() -> None:
    session, _, presentation = _session_with_presentation()
    handlers.ACTIONS["close_presentation"](session, {"save": True})
    presentation.Save.assert_called_once()
    presentation.Close.assert_called_once()
    assert session.powerpoint_presentation is None


# --- slide addressing --------------------------------------------------


def test_slide_by_index_out_of_range_raises() -> None:
    session, _, presentation = _session_with_presentation()
    presentation.Slides.Count = 2
    with pytest.raises(OfficeCommandError, match="Нет слайда номер 5"):
        handlers._slide_by_index(presentation, 5)


def test_slide_by_index_is_native_one_based() -> None:
    session, _, presentation = _session_with_presentation()
    presentation.Slides.Count = 3
    slide = handlers._slide_by_index(presentation, 2)
    presentation.Slides.assert_called_once_with(2)
    assert slide is presentation.Slides.return_value


def test_target_slide_falls_back_to_current_when_no_index() -> None:
    session, _, presentation = _session_with_presentation()
    slide = handlers._target_slide(presentation, {})
    assert slide is presentation.Application.ActiveWindow.View.Slide


def test_add_slide_defaults_to_appending_at_the_end() -> None:
    session, _, presentation = _session_with_presentation()
    presentation.Slides.Count = 4

    result = handlers.ACTIONS["add_slide"](session, {})

    presentation.Slides.Add.assert_called_once_with(Index=5, Layout=2)
    assert result == {"index": 5}


def test_add_slide_inserts_at_requested_index() -> None:
    session, _, presentation = _session_with_presentation()
    presentation.Slides.Count = 4

    result = handlers.ACTIONS["add_slide"](session, {"index": 2})

    presentation.Slides.Add.assert_called_once_with(Index=2, Layout=2)
    assert result == {"index": 2}


def test_delete_slide_refuses_to_remove_the_last_slide() -> None:
    session, _, presentation = _session_with_presentation()
    presentation.Slides.Count = 1
    with pytest.raises(OfficeCommandError, match="последний"):
        handlers.ACTIONS["delete_slide"](session, {"index": 1})


def test_delete_slide_deletes_the_target_slide() -> None:
    session, _, presentation = _session_with_presentation()
    presentation.Slides.Count = 3
    handlers.ACTIONS["delete_slide"](session, {"index": 2})
    presentation.Slides.return_value.Delete.assert_called_once()


def test_duplicate_slide_calls_duplicate_on_the_target() -> None:
    session, _, presentation = _session_with_presentation()
    presentation.Slides.Count = 2
    handlers.ACTIONS["duplicate_slide"](session, {"index": 1})
    presentation.Slides.return_value.Duplicate.assert_called_once()


def test_go_to_slide_uses_view_goto_slide() -> None:
    session, _, presentation = _session_with_presentation()
    presentation.Slides.Count = 3
    slide = presentation.Slides.return_value
    slide.SlideIndex = 2

    handlers.ACTIONS["go_to_slide"](session, {"index": 2})

    presentation.Application.ActiveWindow.View.GotoSlide.assert_called_once_with(2)


# --- title/body/layout/format -------------------------------------------


def test_set_slide_title_requires_has_title() -> None:
    session, _, presentation = _session_with_presentation()
    presentation.Slides.Count = 1
    slide = presentation.Slides.return_value
    slide.Layout = handlers._LAYOUT_TITLE_CONTENT
    slide.Shapes.Count = 1
    slide.Shapes.HasTitle = False

    with pytest.raises(OfficeCommandError, match="title"):
        handlers.ACTIONS["set_slide_title"](session, {"text": "x", "index": 1})


def test_set_slide_title_sets_text_range() -> None:
    session, _, presentation = _session_with_presentation()
    presentation.Slides.Count = 1
    slide = presentation.Slides.return_value
    slide.Layout = handlers._LAYOUT_TITLE_CONTENT
    slide.Shapes.Count = 1
    slide.Shapes.HasTitle = True

    handlers.ACTIONS["set_slide_title"](session, {"text": "Привет", "index": 1})

    assert slide.Shapes.Title.TextFrame.TextRange.Text == "Привет"


def test_set_slide_body_promotes_blank_slide_to_content_layout() -> None:
    session, _, presentation = _session_with_presentation()
    presentation.Slides.Count = 1
    slide = presentation.Slides.return_value
    slide.Layout = handlers._LAYOUT_BLANK

    handlers.ACTIONS["set_slide_body"](session, {"text": "тело", "index": 1})

    assert slide.Layout == handlers._LAYOUT_TITLE_CONTENT
    slide.Shapes.Placeholders.assert_called_once_with(2)


def test_set_slide_body_joins_items_with_newline() -> None:
    session, _, presentation = _session_with_presentation()
    presentation.Slides.Count = 1
    slide = presentation.Slides.return_value
    slide.Layout = handlers._LAYOUT_TITLE_CONTENT
    slide.Shapes.Count = 2

    handlers.ACTIONS["set_slide_body"](session, {"items": ["a", "b"], "index": 1})

    placeholder = slide.Shapes.Placeholders.return_value
    assert placeholder.TextFrame.TextRange.Text == "a\nb"


def test_set_slide_layout_rejects_unknown_layout() -> None:
    session, _, presentation = _session_with_presentation()
    with pytest.raises(OfficeCommandError, match="макет"):
        handlers.ACTIONS["set_slide_layout"](session, {"layout": "two_content"})


def test_set_slide_layout_blank_maps_to_ppLayoutBlank() -> None:
    session, _, presentation = _session_with_presentation()
    handlers.ACTIONS["set_slide_layout"](session, {"layout": "blank"})
    assert presentation.Application.ActiveWindow.View.Slide.Layout == 12


def test_set_slide_text_format_uses_mso_tristate_not_bare_bool() -> None:
    session, _, presentation = _session_with_presentation()
    presentation.Slides.Count = 1
    slide = presentation.Slides.return_value
    slide.Layout = handlers._LAYOUT_TITLE_CONTENT
    slide.Shapes.HasTitle = True

    handlers.ACTIONS["set_slide_text_format"](session, {"target": "title", "bold": True, "index": 1})

    font = slide.Shapes.Title.TextFrame.TextRange.Font
    assert font.Bold == -1  # msoTrue, not Python True/1


def test_set_slide_text_format_color_uses_font_color_rgb() -> None:
    session, _, presentation = _session_with_presentation()
    presentation.Slides.Count = 1
    slide = presentation.Slides.return_value
    slide.Layout = handlers._LAYOUT_TITLE_CONTENT
    slide.Shapes.HasTitle = True

    handlers.ACTIONS["set_slide_text_format"](session, {"target": "title", "color": "#FF0000", "index": 1})

    font = slide.Shapes.Title.TextFrame.TextRange.Font
    assert font.Color.RGB == 0x0000FF  # red -> BGR


def test_set_slide_text_format_rejects_unknown_target() -> None:
    session, _, presentation = _session_with_presentation()
    with pytest.raises(OfficeCommandError, match="область слайда"):
        handlers.ACTIONS["set_slide_text_format"](session, {"target": "footer"})
