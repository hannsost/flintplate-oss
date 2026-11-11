"""CV Parser – main entry point – Sprint 0.3.

Orchestrates:
  1. PDF  → GPT-4o Vision (page images)          ← best for two-column / graphical CVs
  2. DOCX → python-docx text → LangChain + GPT-4o structured extraction
  3. Regex fallback if LLM unavailable
"""

from __future__ import annotations

import logging

from app.ai.parsers.schemas import ParsedCV  # noqa: F401  (re-export for callers)

log = logging.getLogger(__name__)


async def parse_cv_file(file_path: str, original_filename: str = "") -> ParsedCV:
    """Extract and parse a CV file end-to-end.

    Args:
        file_path: Absolute path to the uploaded file.
        original_filename: Used to detect file type when suffix is ambiguous.

    Returns:
        ParsedCV with extracted fields and Trust-Layer source annotations.
    """
    from pathlib import Path

    suffix = Path(file_path).suffix.lower()

    # ── PDF: render pages as images and parse with GPT-4o vision ─────────────
    if suffix == ".pdf":
        try:
            from app.ai.ocr.extractor import pdf_to_images_base64
            from app.ai.parsers.llm_parser import parse_with_llm_vision

            pages_b64 = pdf_to_images_base64(file_path)
            if pages_b64:
                return await parse_with_llm_vision(pages_b64)
            log.warning("pdf_to_images_base64 returned no pages for %s", file_path)
        except Exception:
            log.exception("PDF→vision path failed for %s, falling back to text", file_path)

    # ── DOCX / fallback: extract text then parse with LLM ────────────────────
    from app.ai.ocr.extractor import extract_text
    from app.ai.parsers.llm_parser import parse_with_llm

    raw_text, pages = await extract_text(file_path)
    return await parse_with_llm(raw_text, pages)
