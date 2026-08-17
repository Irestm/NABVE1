from __future__ import annotations

from pathlib import Path

import pytest

from modules.wordpress_bridge import content_processor


def _write_docx(path: Path, paragraphs: list[str]) -> None:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    document.save(str(path))


def test_docx_to_html_converts_paragraphs(tmp_path: Path) -> None:
    pytest.importorskip("mammoth")
    docx_path = tmp_path / "note.docx"
    _write_docx(docx_path, ["Первый абзац.", "Второй абзац."])

    html = content_processor.docx_to_html(str(docx_path))

    assert "Первый абзац." in html
    assert "Второй абзац." in html
    assert "<p>" in html


def test_docx_to_html_missing_file(tmp_path: Path) -> None:
    pytest.importorskip("mammoth")
    with pytest.raises(ValueError):
        content_processor.docx_to_html(str(tmp_path / "missing.docx"))


def test_pdf_to_html_missing_file(tmp_path: Path) -> None:
    pytest.importorskip("pypdf")
    with pytest.raises(ValueError):
        content_processor.pdf_to_html(str(tmp_path / "missing.pdf"))


def test_build_draft_content_mixes_text_and_images(tmp_path: Path) -> None:
    pytest.importorskip("mammoth")
    docx_path = tmp_path / "article.docx"
    _write_docx(docx_path, ["Текст статьи."])
    image_path = tmp_path / "cover.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    inline_image_path = tmp_path / "inline.jpg"
    inline_image_path.write_bytes(b"\xff\xd8\xff fake jpg")

    draft = content_processor.build_draft_content(
        [str(docx_path), str(image_path), str(inline_image_path)]
    )

    assert draft.title == "Article"
    assert "Текст статьи." in draft.html_body
    assert draft.featured_image_path == str(image_path)
    assert draft.image_paths == [str(image_path), str(inline_image_path)]
    assert "inline.jpg" in draft.html_body


def test_build_draft_content_title_hint_overrides_filename(tmp_path: Path) -> None:
    pytest.importorskip("mammoth")
    docx_path = tmp_path / "whatever.docx"
    _write_docx(docx_path, ["Текст."])

    draft = content_processor.build_draft_content([str(docx_path)], title_hint="Мой заголовок")

    assert draft.title == "Мой заголовок"


def test_build_draft_content_skips_unsupported_files(tmp_path: Path) -> None:
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("just text")

    draft = content_processor.build_draft_content([str(unsupported)])

    assert draft.html_body == ""
    assert draft.image_paths == []
