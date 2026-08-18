from __future__ import annotations

from pathlib import Path

import pytest

from modules.files import service_layer


class _FakeConverter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def convert_to_pdf(self, path: str, output_dir: str | None) -> Path:
        self.calls.append(("convert_to_pdf", path, output_dir))
        return Path(path).with_suffix(".pdf")

    def read_docx_text(self, path: str) -> str:
        self.calls.append(("read_docx_text", path))
        return "text"

    def read_xlsx_sheet(self, path: str, sheet_name: str | None) -> list[list[object]]:
        self.calls.append(("read_xlsx_sheet", path, sheet_name))
        return [["a"]]


def test_convert_to_pdf_raises_when_path_missing() -> None:
    with pytest.raises(ValueError, match="путь"):
        service_layer.convert_to_pdf(_FakeConverter(), None, None)


def test_convert_to_pdf_delegates_to_converter() -> None:
    converter = _FakeConverter()

    result = service_layer.convert_to_pdf(converter, "/tmp/doc.docx", "/tmp/out")

    assert result == Path("/tmp/doc.pdf")
    assert converter.calls == [("convert_to_pdf", "/tmp/doc.docx", "/tmp/out")]


def test_read_docx_text_raises_when_path_missing() -> None:
    with pytest.raises(ValueError, match="путь"):
        service_layer.read_docx_text(_FakeConverter(), "")


def test_read_docx_text_delegates_to_converter() -> None:
    converter = _FakeConverter()

    result = service_layer.read_docx_text(converter, "/tmp/doc.docx")

    assert result == "text"


def test_read_xlsx_sheet_raises_when_path_missing() -> None:
    with pytest.raises(ValueError, match="путь"):
        service_layer.read_xlsx_sheet(_FakeConverter(), None, None)


def test_read_xlsx_sheet_delegates_to_converter() -> None:
    converter = _FakeConverter()

    result = service_layer.read_xlsx_sheet(converter, "/tmp/data.xlsx", "Sheet1")

    assert result == [["a"]]
    assert converter.calls == [("read_xlsx_sheet", "/tmp/data.xlsx", "Sheet1")]
