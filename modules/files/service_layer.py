from __future__ import annotations

from pathlib import Path
from typing import Any

from modules.files.ports import FileConverterPort


def convert_to_pdf(converter: FileConverterPort, path: str | None, output_dir: str | None) -> Path:
    if not path:
        raise ValueError("Missing required parameter 'path'")
    return converter.convert_to_pdf(path, output_dir)


def read_docx_text(converter: FileConverterPort, path: str | None) -> str:
    if not path:
        raise ValueError("Missing required parameter 'path'")
    return converter.read_docx_text(path)


def read_xlsx_sheet(
    converter: FileConverterPort, path: str | None, sheet_name: str | None
) -> list[list[Any]]:
    if not path:
        raise ValueError("Missing required parameter 'path'")
    return converter.read_xlsx_sheet(path, sheet_name)
