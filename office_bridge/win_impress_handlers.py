"""win32com action handlers for the Windows Jarvis <-> PowerPoint bridge —
the Windows counterpart of office_bridge/impress_handlers.py.

Same ACTIONS vocabulary/params as the Linux/UNO side, reimplemented against
PowerPoint's COM object model. Slides are natively 1-based in PowerPoint's
own Slides collection (unlike UNO's 0-based DrawPages), so index handling
here is simpler than the Linux side's zero_based conversions. Not exercised
against a real PowerPoint install — see office_bridge/server_win.py's module
docstring.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from win_session import OfficeCommandError, WinOfficeSession, bgr_color

# PpSlideLayout: ppLayoutText=2 ("Title, Text" — the closest built-in
# equivalent to the Linux side's title+content AutoLayout), ppLayoutBlank=12.
_LAYOUT_TITLE_CONTENT = 2
_LAYOUT_BLANK = 12
# ppAlignLeft/Center/Right/Justify.
_PP_ALIGN_BY_NAME: dict[str, int] = {"left": 1, "center": 2, "right": 3, "justify": 4}
# PowerPoint's own placeholder ordering for a ppLayoutText slide: index 1 is
# always the title, index 2 the body/content text placeholder.
_TITLE_PLACEHOLDER_INDEX = 1
_BODY_PLACEHOLDER_INDEX = 2
# MsoTriState — PowerPoint's Font.Bold/Italic/Underline are NOT plain COM
# booleans like Word's/Excel's (msoTrue=-1, msoFalse=0, and a bare Python
# True/False would coerce to 1/0 over COM, which is NOT the same value as
# msoTrue) — assign these explicit ints, never a bare bool, for any
# PowerPoint Font tri-state property.
_MSO_TRUE = -1
_MSO_FALSE = 0


def _require(params: dict[str, Any], key: str) -> Any:
    value = params.get(key)
    if value in (None, ""):
        raise OfficeCommandError(f"Не указан обязательный параметр '{key}'")
    return value


def _abs_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _slide_by_index(presentation: Any, index: int) -> Any:
    slides = presentation.Slides
    if index < 1 or index > slides.Count:
        raise OfficeCommandError(f"Нет слайда номер {index} (всего слайдов: {slides.Count})")
    return slides(index)


def _current_slide(presentation: Any) -> Any:
    # The slide currently shown in the presentation's active window — closest
    # PowerPoint COM equivalent to UNO's getCurrentPage(), requires the
    # presentation window to actually be open (true for this bridge's
    # always-visible live-editing session).
    return presentation.Application.ActiveWindow.View.Slide


def _target_slide(presentation: Any, params: dict[str, Any]) -> Any:
    index = params.get("index")
    if index is not None:
        return _slide_by_index(presentation, int(index))
    return _current_slide(presentation)


def _ensure_content_layout(slide: Any) -> None:
    if slide.Layout == _LAYOUT_BLANK or slide.Shapes.Count == 0:
        slide.Layout = _LAYOUT_TITLE_CONTENT


def _shape_for_target(slide: Any, target: str) -> Any:
    _ensure_content_layout(slide)
    if target == "title":
        if not slide.Shapes.HasTitle:
            raise OfficeCommandError("У этого слайда нет области 'title'")
        return slide.Shapes.Title
    try:
        return slide.Shapes.Placeholders(_BODY_PLACEHOLDER_INDEX)
    except Exception as exc:
        raise OfficeCommandError("У этого слайда нет области 'body'") from exc


def _open_presentation(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    path = params.get("path")
    if path and os.path.exists(_abs_path(path)):
        presentation = session.powerpoint_app.Presentations.Open(_abs_path(path))
    else:
        presentation = session.powerpoint_app.Presentations.Add()
        if path:
            presentation.SaveAs(_abs_path(path))
    session.powerpoint_presentation = presentation
    return {"opened": path or "новая презентация"}


def _save_presentation(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    presentation = session.require_powerpoint_presentation()
    path = params.get("path")
    if path:
        presentation.SaveAs(_abs_path(path))
    else:
        if not presentation.Path:
            raise OfficeCommandError("У презентации ещё нет пути на диске — укажи, куда сохранить.")
        presentation.Save()
    return {}


def _close_presentation(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    presentation = session.require_powerpoint_presentation()
    if params.get("save"):
        _save_presentation(session, {})
    presentation.Close()
    session.powerpoint_presentation = None
    return {}


def _impress_undo(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    # Unlike Word, PowerPoint's Application object has no direct Undo()
    # method in its COM object model — CommandBars.ExecuteMso("Undo") (the
    # same mechanism as triggering the ribbon button) is the commonly used
    # automation workaround, but this is the least-verified of the four
    # apps' undo/redo actions and its reliability outside an interactive,
    # focused PowerPoint window is genuinely uncertain without a real
    # install to test against.
    session.require_powerpoint_presentation()
    session.powerpoint_app.CommandBars.ExecuteMso("Undo")
    return {}


def _impress_redo(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    session.require_powerpoint_presentation()
    session.powerpoint_app.CommandBars.ExecuteMso("Redo")
    return {}


def _add_slide(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    presentation = session.require_powerpoint_presentation()
    slides = presentation.Slides
    index = params.get("index")
    insert_at = int(index) if index is not None else slides.Count + 1
    insert_at = max(1, min(insert_at, slides.Count + 1))
    slides.Add(Index=insert_at, Layout=_LAYOUT_TITLE_CONTENT)
    return {"index": insert_at}


def _delete_slide(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    presentation = session.require_powerpoint_presentation()
    slide = _slide_by_index(presentation, int(_require(params, "index")))
    if presentation.Slides.Count <= 1:
        raise OfficeCommandError("Нельзя удалить последний оставшийся слайд")
    slide.Delete()
    return {}


def _duplicate_slide(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    presentation = session.require_powerpoint_presentation()
    slide = _slide_by_index(presentation, int(_require(params, "index")))
    # Slide.Duplicate() inserts the copy immediately after the original and
    # shifts every later slide's index by +1 — same documented gotcha as
    # impress_handlers.py's _duplicate_slide (see AGENT_NOTES.md).
    slide.Duplicate()
    return {}


def _go_to_slide(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    presentation = session.require_powerpoint_presentation()
    slide = _slide_by_index(presentation, int(_require(params, "index")))
    presentation.Application.ActiveWindow.View.GotoSlide(slide.SlideIndex)
    return {}


def _set_slide_title(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    presentation = session.require_powerpoint_presentation()
    text = str(_require(params, "text"))
    slide = _target_slide(presentation, params)
    _shape_for_target(slide, "title").TextFrame.TextRange.Text = text
    return {}


def _set_slide_body(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    presentation = session.require_powerpoint_presentation()
    slide = _target_slide(presentation, params)
    items = params.get("items")
    if isinstance(items, list) and items:
        text = "\n".join(str(item) for item in items)
    else:
        text = str(_require(params, "text"))
    _shape_for_target(slide, "body").TextFrame.TextRange.Text = text
    return {}


def _set_slide_layout(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    presentation = session.require_powerpoint_presentation()
    layout_name = str(_require(params, "layout")).lower()
    layout = {"title_content": _LAYOUT_TITLE_CONTENT, "blank": _LAYOUT_BLANK}.get(layout_name)
    if layout is None:
        raise OfficeCommandError(f"Неизвестный макет слайда: {layout_name}")
    _target_slide(presentation, params).Layout = layout
    return {}


def _set_slide_text_format(session: WinOfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    presentation = session.require_powerpoint_presentation()
    target = str(params.get("target", "title"))
    if target not in ("title", "body"):
        raise OfficeCommandError(f"Неизвестная область слайда: {target}")
    slide = _target_slide(presentation, params)
    text_range = _shape_for_target(slide, target).TextFrame.TextRange
    font = text_range.Font

    if "bold" in params:
        font.Bold = _MSO_TRUE if params["bold"] else _MSO_FALSE
    if "italic" in params:
        font.Italic = _MSO_TRUE if params["italic"] else _MSO_FALSE
    if "underline" in params:
        font.Underline = _MSO_TRUE if params["underline"] else _MSO_FALSE
    if "font_size" in params:
        font.Size = float(params["font_size"])
    if "color" in params:
        font.Color.RGB = bgr_color(params["color"])
    if "align" in params:
        alignment = _PP_ALIGN_BY_NAME.get(str(params["align"]).lower())
        if alignment is None:
            raise OfficeCommandError(f"Неизвестное выравнивание: {params['align']}")
        text_range.ParagraphFormat.Alignment = alignment
    return {}


ACTIONS: dict[str, Callable[[WinOfficeSession, dict[str, Any]], dict[str, Any]]] = {
    "open_presentation": _open_presentation,
    "save_presentation": _save_presentation,
    "close_presentation": _close_presentation,
    "impress_undo": _impress_undo,
    "impress_redo": _impress_redo,
    "add_slide": _add_slide,
    "delete_slide": _delete_slide,
    "duplicate_slide": _duplicate_slide,
    "go_to_slide": _go_to_slide,
    "set_slide_title": _set_slide_title,
    "set_slide_body": _set_slide_body,
    "set_slide_layout": _set_slide_layout,
    "set_slide_text_format": _set_slide_text_format,
}
