from __future__ import annotations

import asyncio
from typing import Any

from core.dispatcher import CommandDispatcher
from modules.files import service_layer
from modules.files.converter import LibreOfficeFileConverter
from modules.files.ports import FileConverterPort

_converter: FileConverterPort = LibreOfficeFileConverter()


async def _handle_convert_to_pdf(params: dict[str, Any]) -> dict[str, Any]:
    result_path = await asyncio.to_thread(
        service_layer.convert_to_pdf, _converter, params.get("path"), params.get("output_dir")
    )
    return {"path": str(result_path)}


async def _handle_read_docx_text(params: dict[str, Any]) -> dict[str, Any]:
    text = await asyncio.to_thread(service_layer.read_docx_text, _converter, params.get("path"))
    return {"text": text}


async def _handle_read_xlsx_sheet(params: dict[str, Any]) -> dict[str, Any]:
    rows = await asyncio.to_thread(
        service_layer.read_xlsx_sheet, _converter, params.get("path"), params.get("sheet_name")
    )
    return {"rows": rows}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "convert_to_pdf",
        _handle_convert_to_pdf,
        dangerous=False,
        description="Convert a file to PDF using LibreOffice headless (path, optional output_dir).",
    )
    dispatcher.register(
        "read_docx_text",
        _handle_read_docx_text,
        dangerous=False,
        description="Read and return all text from a .docx file (path).",
    )
    dispatcher.register(
        "read_xlsx_sheet",
        _handle_read_xlsx_sheet,
        dangerous=False,
        description="Read a sheet from a .xlsx file as rows of cell values (path, optional sheet_name).",
    )
