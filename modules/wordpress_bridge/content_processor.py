from __future__ import annotations

from pathlib import Path

from core.logger import get_logger
from modules.wordpress_bridge.domain import DraftContent

logger = get_logger(__name__)

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def docx_to_html(path: str) -> str:
    try:
        import mammoth
    except ImportError as exc:
        raise RuntimeError("mammoth is not installed. Install it with: pip install mammoth") from exc

    source = Path(path)
    if not source.is_file():
        raise ValueError(f"File not found: {path}")

    with source.open("rb") as handle:
        result = mammoth.convert_to_html(handle)
    for warning in result.messages:
        logger.debug("mammoth warning converting %s: %s", path, warning)
    return result.value


def pdf_to_html(path: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is not installed. Install it with: pip install pypdf") from exc

    source = Path(path)
    if not source.is_file():
        raise ValueError(f"File not found: {path}")

    reader = PdfReader(str(source))
    paragraphs: list[str] = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        for line in text.split("\n"):
            line = line.strip()
            if line:
                paragraphs.append(f"<p>{line}</p>")
    return "\n".join(paragraphs)


def _title_from_filename(path: str) -> str:
    return Path(path).stem.replace("_", " ").replace("-", " ").strip().capitalize()


def build_draft_content(file_paths: list[str], *, title_hint: str | None = None) -> DraftContent:
    """Turns whatever the WordPress plugin uploaded (docx/pdf/images, any
    mix) into one DraftContent: docx/pdf become the HTML body (concatenated
    in upload order), images are collected as-is for wp_draft_publisher.py
    to upload as WordPress media — the first image becomes the featured
    image, the rest are appended as inline <img> tags at the end of the
    body."""
    html_parts: list[str] = []
    image_paths: list[str] = []
    first_text_file: str | None = None

    for file_path in file_paths:
        suffix = Path(file_path).suffix.lower()
        if suffix == ".docx":
            html_parts.append(docx_to_html(file_path))
            first_text_file = first_text_file or file_path
        elif suffix == ".pdf":
            html_parts.append(pdf_to_html(file_path))
            first_text_file = first_text_file or file_path
        elif suffix in _IMAGE_SUFFIXES:
            image_paths.append(file_path)
        else:
            logger.warning("Skipping unsupported file type for WordPress draft: %s", file_path)

    title = title_hint or (_title_from_filename(first_text_file) if first_text_file else "Новый черновик")
    featured_image_path = image_paths[0] if image_paths else None
    inline_images = image_paths[1:]

    body = "\n".join(html_parts)
    if inline_images:
        body += "\n" + "\n".join(f'<img src="{Path(p).name}" alt="" />' for p in inline_images)

    return DraftContent(
        title=title,
        html_body=body,
        image_paths=image_paths,
        featured_image_path=featured_image_path,
    )


async def rewrite_html_for_blog(html_body: str) -> str:
    """Optional pass through modules.ai_bridge to clean up/rewrite the raw
    extracted HTML into something more blog-appropriate. Best-effort: on any
    failure (no provider logged in, browser automation error, ...) the
    original HTML is returned unchanged rather than blocking the whole
    draft on it — the user still gets a usable draft to edit by hand."""
    from modules.ai_bridge.provider_manager import get_provider_manager

    prompt = (
        "Отформатируй следующий HTML-текст для публикации в блоге WordPress: "
        "поправь абзацы, добавь подзаголовки (h2/h3) где это уместно, не меняй "
        "смысл и не добавляй ничего нового. Верни ТОЛЬКО итоговый HTML, без "
        f"пояснений.\n\n{html_body}"
    )
    try:
        return await get_provider_manager().send_prompt(prompt, fast_mode=True)
    except Exception:
        logger.exception("AI rewrite of WordPress draft HTML failed; using the unrewritten HTML")
        return html_body
