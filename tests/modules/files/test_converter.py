from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.files import converter


def test_read_docx_text_round_trips_written_content(tmp_path) -> None:
    path = tmp_path / "note.docx"
    converter.write_docx_text(str(path), "первая строка\nвторая строка")

    text = converter.read_docx_text(str(path))

    assert text == "первая строка\nвторая строка"


def test_read_docx_text_raises_for_missing_file(tmp_path) -> None:
    with pytest.raises(ValueError, match="не найден"):
        converter.read_docx_text(str(tmp_path / "missing.docx"))


def test_write_docx_text_creates_parent_directories(tmp_path) -> None:
    path = tmp_path / "nested" / "note.docx"

    result = converter.write_docx_text(str(path), "текст")

    assert result == path
    assert path.is_file()


def test_read_xlsx_sheet_round_trips_written_rows(tmp_path) -> None:
    path = tmp_path / "data.xlsx"
    rows = [["Имя", "Возраст"], ["Аня", 30]]
    converter.write_xlsx_sheet(str(path), rows)

    result = converter.read_xlsx_sheet(str(path))

    assert result == rows


def test_read_xlsx_sheet_raises_for_missing_file(tmp_path) -> None:
    with pytest.raises(ValueError, match="не найден"):
        converter.read_xlsx_sheet(str(tmp_path / "missing.xlsx"))


def test_write_xlsx_sheet_uses_given_sheet_name(tmp_path) -> None:
    path = tmp_path / "data.xlsx"

    converter.write_xlsx_sheet(str(path), [["a"]], sheet_name="Report")

    result = converter.read_xlsx_sheet(str(path), sheet_name="Report")
    assert result == [["a"]]


def test_convert_to_pdf_raises_for_missing_source(tmp_path) -> None:
    with pytest.raises(ValueError, match="не найден"):
        converter.convert_to_pdf(str(tmp_path / "missing.docx"))


def test_convert_to_pdf_raises_when_soffice_is_not_found(tmp_path, monkeypatch) -> None:
    source = tmp_path / "doc.docx"
    source.write_text("x")
    monkeypatch.setattr(converter.shutil, "which", lambda _cmd: None)
    monkeypatch.setattr(converter.Path, "exists", lambda self: False)

    with pytest.raises(RuntimeError, match="LibreOffice"):
        converter.convert_to_pdf(str(source))


def test_convert_to_pdf_raises_on_nonzero_exit_code(tmp_path, monkeypatch) -> None:
    source = tmp_path / "doc.docx"
    source.write_text("x")
    monkeypatch.setattr(converter, "_find_soffice", lambda: "/usr/bin/soffice")
    monkeypatch.setattr(
        converter.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="boom"),
    )

    with pytest.raises(RuntimeError, match="boom"):
        converter.convert_to_pdf(str(source))


def test_convert_to_pdf_raises_when_output_file_is_missing(tmp_path, monkeypatch) -> None:
    source = tmp_path / "doc.docx"
    source.write_text("x")
    monkeypatch.setattr(converter, "_find_soffice", lambda: "/usr/bin/soffice")
    monkeypatch.setattr(
        converter.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    with pytest.raises(RuntimeError, match="no output file"):
        converter.convert_to_pdf(str(source))


def test_convert_to_pdf_returns_output_path_on_success(tmp_path, monkeypatch) -> None:
    source = tmp_path / "doc.docx"
    source.write_text("x")
    monkeypatch.setattr(converter, "_find_soffice", lambda: "/usr/bin/soffice")

    def _fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        (tmp_path / "doc.pdf").write_text("pdf-bytes")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(converter.subprocess, "run", _fake_run)

    result = converter.convert_to_pdf(str(source))

    assert result == tmp_path / "doc.pdf"
