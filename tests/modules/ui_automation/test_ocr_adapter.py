from __future__ import annotations

import pytesseract

from core.os_adapter.base import ActiveWindow
from modules.ui_automation.ocr_adapter import OcrElementInspector


class _FakeImage:
    pass


def test_filters_low_confidence_and_empty_words(monkeypatch) -> None:
    monkeypatch.setattr(
        "modules.ui_automation.ocr_adapter.capture_window",
        lambda active: (_FakeImage(), (100, 50)),
    )
    fake_data = {
        "text": ["Сохранить", "", "  ", "мусор"],
        "conf": ["95", "80", "70", "10"],
        "left": [10, 0, 0, 5],
        "top": [20, 0, 0, 8],
        "width": [60, 0, 0, 30],
        "height": [15, 0, 0, 12],
    }
    monkeypatch.setattr(pytesseract, "image_to_data", lambda image, lang, output_type: fake_data)

    inspector = OcrElementInspector()
    elements = inspector.list_elements(ActiveWindow(title="x", pid=None, bbox=(100, 50, 300, 200)))

    assert [e.name for e in elements] == ["Сохранить"]
    assert elements[0].role == "text"
    # (100, 50) window offset + (10, 20) word position within the screenshot
    assert elements[0].bbox == (110, 70, 60, 15)


def test_returns_empty_list_when_screenshot_capture_fails(monkeypatch) -> None:
    def _raise(active: ActiveWindow) -> None:
        raise RuntimeError("no display")

    monkeypatch.setattr("modules.ui_automation.ocr_adapter.capture_window", _raise)

    inspector = OcrElementInspector()
    assert inspector.list_elements(ActiveWindow(title="x", pid=None)) == []


def test_returns_empty_list_when_ocr_call_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "modules.ui_automation.ocr_adapter.capture_window",
        lambda active: (_FakeImage(), (0, 0)),
    )

    def _raise(image, lang, output_type):
        raise RuntimeError("tesseract not installed")

    monkeypatch.setattr(pytesseract, "image_to_data", _raise)

    inspector = OcrElementInspector()
    assert inspector.list_elements(ActiveWindow(title="x", pid=None)) == []
