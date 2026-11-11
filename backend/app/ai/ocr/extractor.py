"""OCR & text extraction pipeline – Sprint 0.3.

Priority chain per file type:
  PDF  → 1) pypdf (digital text)  2) pdf2image + pytesseract (scanned)
  DOCX → python-docx
  DOC  → raw bytes fallback
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_MIN_PDF_CHARS = 100  # threshold below which we fall back to OCR


async def extract_text(file_path: str) -> tuple[str, list[str]]:
    """Extract text from a PDF, DOCX, DOC, or plain-text file.

    Returns:
        (full_text, pages_text_list) where pages_text_list[i] is the text
        of page i+1.  On any unrecoverable error returns ("", []).
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    try:
        if suffix == ".pdf":
            return await _extract_pdf(file_path)
        elif suffix == ".docx":
            return _extract_docx(file_path)
        else:
            return _extract_plain(file_path)
    except Exception:
        logger.exception("extract_text failed for %s", file_path)
        return ("", [])


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


async def _extract_pdf(file_path: str) -> tuple[str, list[str]]:
    """Try pypdf first; fall back to pdf2image + pytesseract for scanned PDFs."""
    pages = _pypdf_extract(file_path)
    full_text = "\n".join(pages)

    if len(full_text.strip()) >= _MIN_PDF_CHARS:
        return (full_text, pages)

    logger.info("pypdf yielded < %d chars for %s – switching to OCR", _MIN_PDF_CHARS, file_path)
    pages = _ocr_extract(file_path)
    return ("\n".join(pages), pages)


def _pypdf_extract(file_path: str) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(file_path)
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text)
    return pages


def pdf_to_images_base64(file_path: str, max_pages: int = 6, dpi: int = 150) -> list[str]:
    """Render PDF pages to base64 JPEG strings for GPT-4o vision.

    Args:
        file_path: Path to the PDF file.
        max_pages: Maximum number of pages to render (most CVs are ≤ 3).
        dpi: Resolution – 150 Dpi is a good balance between quality and token cost.

    Returns:
        List of base64-encoded JPEG strings, one per page.
    """
    import base64
    from io import BytesIO

    from pdf2image import convert_from_path

    images = convert_from_path(file_path, dpi=dpi, first_page=1, last_page=max_pages)
    result: list[str] = []
    for img in images:
        # Downscale if wider than 1 500 px to stay within vision token budget
        if img.width > 1500:
            ratio = 1500 / img.width
            img = img.resize((1500, int(img.height * ratio)))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        result.append(base64.b64encode(buf.getvalue()).decode())
    return result


def _ocr_extract(file_path: str) -> list[str]:
    import pytesseract
    from pdf2image import convert_from_path

    images = convert_from_path(file_path)
    pages: list[str] = []
    for img in images:
        text: str = pytesseract.image_to_string(img)
        pages.append(text)
    return pages


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def _extract_docx(file_path: str) -> tuple[str, list[str]]:
    from docx import Document

    doc = Document(file_path)
    paragraphs = [para.text for para in doc.paragraphs]
    full_text = "\n".join(paragraphs)
    # DOCX has no inherent page structure – return the whole text as one "page"
    return (full_text, [full_text])


# ---------------------------------------------------------------------------
# Plain text / DOC fallback
# ---------------------------------------------------------------------------


def _extract_plain(file_path: str) -> tuple[str, list[str]]:
    try:
        text = Path(file_path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = Path(file_path).read_text(encoding="latin-1", errors="replace")
    return (text, [text])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_page_source(page_idx: int) -> str:
    """Return a human-readable source label for a page index (0-based)."""
    return f"cv_page_{page_idx + 1}"
