"""UNO action handlers for the Jarvis <-> LibreOffice Impress bridge.

Same shape as writer_handlers.py/calc_handlers.py — (session: OfficeSession,
params: dict) -> dict. Like Calc, every action names an explicit target
(slide `index`, 1-based) rather than relying on a cursor/selection concept;
unlike Calc, a slide's content lives in a small, fixed set of placeholder
shapes rather than arbitrary cells, so text/formatting actions address a
shape by `target` ("title"|"body") instead of a free-form reference.

Empirically verified against a live LibreOffice 24.2 (see AGENT_NOTES.md):
a slide's Layout property is a plain AutoLayout int (1 = title+content, the
only non-blank layout this module sets; 20 = blank, what a freshly inserted
slide starts as) — shape index 0 is always the title placeholder once a
non-blank layout is set, index 1 the content/outline placeholder below it.
"""

from __future__ import annotations

import os
from typing import Any, Callable

import uno

from office_session import OfficeCommandError, OfficeSession, prop as _prop

_FILTER_BY_EXTENSION: dict[str, str] = {
    ".pptx": "Impress MS PowerPoint 2007 XML",
    ".ppt": "MS PowerPoint 97",
    ".odp": "impress8",
    ".pdf": "impress_pdf_Export",
}

_PARA_ADJUST_BY_NAME: dict[str, str] = {
    "left": "LEFT",
    "right": "RIGHT",
    "center": "CENTER",
    "justify": "BLOCK",
}

# com.sun.star.presentation.DrawPage's Layout is a plain int, not an enum —
# only the two layouts this module ever sets. Any other slide layout a
# document already has (title-only, two-content, ...) is left as-is; v1
# only creates/normalizes to one of these two.
_LAYOUT_TITLE_CONTENT = 1
_LAYOUT_BLANK = 20
_TITLE_SHAPE_INDEX = 0
_BODY_SHAPE_INDEX = 1


def _require(params: dict[str, Any], key: str) -> Any:
    value = params.get(key)
    if value in (None, ""):
        raise OfficeCommandError(f"Не указан обязательный параметр '{key}'")
    return value


def _to_file_url(path: str) -> str:
    return uno.systemPathToFileUrl(os.path.abspath(os.path.expanduser(path)))


def _slide_by_index(document: Any, index_1_based: int) -> Any:
    slides = document.DrawPages
    zero_based = index_1_based - 1
    if zero_based < 0 or zero_based >= slides.Count:
        raise OfficeCommandError(f"Нет слайда номер {index_1_based} (всего слайдов: {slides.Count})")
    return slides.getByIndex(zero_based)


def _current_slide(document: Any) -> Any:
    return document.getCurrentController().getCurrentPage()


def _target_slide(document: Any, params: dict[str, Any]) -> Any:
    index = params.get("index")
    if index is not None:
        return _slide_by_index(document, int(index))
    return _current_slide(document)


def _ensure_content_layout(slide: Any) -> None:
    """A freshly inserted slide starts blank (Layout 20, no shapes) — text
    actions need somewhere to put the title/body, so a blank slide is
    promoted to the title+content layout the moment text is asked for."""
    if slide.Layout == _LAYOUT_BLANK or slide.Count == 0:
        slide.Layout = _LAYOUT_TITLE_CONTENT


def _shape_for_target(slide: Any, target: str) -> Any:
    _ensure_content_layout(slide)
    index = _TITLE_SHAPE_INDEX if target == "title" else _BODY_SHAPE_INDEX
    if index >= slide.Count:
        raise OfficeCommandError(f"У этого слайда нет области '{target}'")
    return slide.getByIndex(index)


def _open_presentation(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    path = params.get("path")
    if path and os.path.exists(os.path.abspath(os.path.expanduser(path))):
        document = session.desktop.loadComponentFromURL(
            _to_file_url(path), "_blank", 0, (_prop("Hidden", False),)
        )
    else:
        # loadComponentFromURL on a path that doesn't exist yet hangs
        # indefinitely rather than erroring — verified empirically
        # (writer_handlers.py hit the same issue first, see
        # AGENT_NOTES.md) — so always create blank and give it the
        # requested location via storeAsURL instead.
        document = session.desktop.loadComponentFromURL(
            "private:factory/simpress", "_blank", 0, (_prop("Hidden", False),)
        )
        if path:
            document.storeAsURL(_to_file_url(path), ())
    session.impress_document = document
    return {"opened": path or "новая презентация"}


def _save_presentation(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_impress_document()
    path = params.get("path")
    if path:
        url = _to_file_url(path)
        filter_name = _FILTER_BY_EXTENSION.get(os.path.splitext(path)[1].lower(), "impress8")
        document.storeToURL(url, (_prop("FilterName", filter_name), _prop("Overwrite", True)))
    else:
        if not document.hasLocation():
            raise OfficeCommandError("У презентации ещё нет пути на диске — укажи, куда сохранить.")
        document.store()
    return {}


def _close_presentation(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_impress_document()
    if params.get("save"):
        _save_presentation(session, {})
    document.close(False)
    session.impress_document = None
    return {}


def _impress_undo(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    session.require_impress_document().getUndoManager().undo()
    return {}


def _impress_redo(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    session.require_impress_document().getUndoManager().redo()
    return {}


def _add_slide(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_impress_document()
    slides = document.DrawPages
    index = params.get("index")
    zero_based = int(index) - 1 if index is not None else slides.Count
    zero_based = max(0, min(zero_based, slides.Count))
    slides.insertNewByIndex(zero_based)
    slides.getByIndex(zero_based).Layout = _LAYOUT_TITLE_CONTENT
    return {"index": zero_based + 1}


def _delete_slide(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_impress_document()
    slide = _slide_by_index(document, int(_require(params, "index")))
    if document.DrawPages.Count <= 1:
        raise OfficeCommandError("Нельзя удалить последний оставшийся слайд")
    document.DrawPages.remove(slide)
    return {}


def _duplicate_slide(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_impress_document()
    slide = _slide_by_index(document, int(_require(params, "index")))
    document.duplicate(slide)
    return {}


def _go_to_slide(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_impress_document()
    slide = _slide_by_index(document, int(_require(params, "index")))
    document.getCurrentController().setCurrentPage(slide)
    return {}


def _set_slide_title(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_impress_document()
    text = str(_require(params, "text"))
    slide = _target_slide(document, params)
    _shape_for_target(slide, "title").setString(text)
    return {}


def _set_slide_body(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_impress_document()
    slide = _target_slide(document, params)
    items = params.get("items")
    if isinstance(items, list) and items:
        text = "\n".join(str(item) for item in items)
    else:
        text = str(_require(params, "text"))
    _shape_for_target(slide, "body").setString(text)
    return {}


def _set_slide_layout(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_impress_document()
    layout_name = str(_require(params, "layout")).lower()
    layout = {"title_content": _LAYOUT_TITLE_CONTENT, "blank": _LAYOUT_BLANK}.get(layout_name)
    if layout is None:
        raise OfficeCommandError(f"Неизвестный макет слайда: {layout_name}")
    _target_slide(document, params).Layout = layout
    return {}


def _set_slide_text_format(session: OfficeSession, params: dict[str, Any]) -> dict[str, Any]:
    document = session.require_impress_document()
    target = str(params.get("target", "title"))
    if target not in ("title", "body"):
        raise OfficeCommandError(f"Неизвестная область слайда: {target}")
    slide = _target_slide(document, params)
    shape = _shape_for_target(slide, target)
    text = shape.getText()
    cursor = text.createTextCursor()
    cursor.gotoStart(False)
    cursor.gotoEnd(True)

    if "bold" in params:
        cursor.CharWeight = 150.0 if params["bold"] else 100.0
    if "italic" in params:
        cursor.CharPosture = uno.Enum(
            "com.sun.star.awt.FontSlant", "ITALIC" if params["italic"] else "NONE"
        )
    if "underline" in params:
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


ACTIONS: dict[str, Callable[[OfficeSession, dict[str, Any]], dict[str, Any]]] = {
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


def dispatch(session: OfficeSession, action: str, params: dict[str, Any]) -> dict[str, Any]:
    handler = ACTIONS.get(action)
    if handler is None:
        raise OfficeCommandError(f"Неизвестное действие: {action}")
    return handler(session, params) or {}
