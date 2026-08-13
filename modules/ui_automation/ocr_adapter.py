from __future__ import annotations

from core.logger import get_logger
from core.os_adapter.base import ActiveWindow
from core.os_adapter.screenshot import capture_window
from modules.ui_automation.domain import UIElement

logger = get_logger(__name__)

# Below this OCR confidence (pytesseract's 0-100 scale; it also emits -1 for
# non-text regions it didn't even attempt to read) a "word" is more likely a
# misread icon or antialiasing artifact than a genuine label worth offering
# the grounding model as a click target.
_MIN_CONFIDENCE = 60
_MAX_ELEMENTS = 200


class OcrElementInspector:
    """Vision-based fallback ElementInspectorPort (see ports.py):
    screenshots the active window and runs local OCR (pytesseract) to turn
    visible text into UIElement candidates, tried only when neither AT-SPI
    nor CDP could enumerate anything — see
    modules/ui_automation/service_layer.py::_list_elements, which is the
    only caller. This is what unblocks Electron/canvas apps that expose no
    accessibility tree at all.

    Coordinates are absolute screen pixels, matching every other UIElement
    source (see core/os_adapter/screenshot.py's offset return value).
    Text-only: unlike a full vision-language-model fallback, this can't
    recognize an icon-only button with no visible label — good enough to
    unblock text-heavy UIs, not a complete replacement for accessibility
    trees."""

    def list_elements(self, active: ActiveWindow) -> list[UIElement]:
        import pytesseract

        try:
            image, (offset_x, offset_y) = capture_window(active)
        except Exception:
            logger.exception("Screenshot capture failed for OCR fallback")
            return []

        try:
            data = pytesseract.image_to_data(
                image, lang="rus+eng", output_type=pytesseract.Output.DICT
            )
        except Exception:
            logger.exception("OCR failed for active window '%s'", active.title)
            return []

        elements: list[UIElement] = []
        for i, text in enumerate(data["text"]):
            word = text.strip()
            if not word:
                continue
            try:
                confidence = int(float(data["conf"][i]))
            except (ValueError, IndexError):
                continue
            if confidence < _MIN_CONFIDENCE:
                continue

            bbox = (
                offset_x + data["left"][i],
                offset_y + data["top"][i],
                data["width"][i],
                data["height"][i],
            )
            elements.append(UIElement(index=len(elements), role="text", name=word, bbox=bbox))
            if len(elements) >= _MAX_ELEMENTS:
                break

        return elements
