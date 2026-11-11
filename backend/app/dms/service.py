"""DMS background processing service (Sprint 3.1).

Handles:
  - OCR text extraction (pypdf for PDFs, pytesseract for images)
  - Thumbnail generation (pdf2image for PDFs, Pillow for images)
  - search_vector update (PostgreSQL tsvector)
  - Thumbnail upload to S3/R2
"""

from __future__ import annotations

import io
import logging
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

_THUMB_MAX_WIDTH = 400  # px
_THUMB_MAX_HEIGHT = 560


async def process_document(document_id: uuid.UUID) -> None:
    """Entry point called via asyncio.ensure_future after upload.

    Fetches document bytes, runs OCR + thumbnail, updates DB.
    """
    async with AsyncSessionLocal() as db:
        try:
            await _run_processing(db, document_id)
        except Exception:
            logger.exception("DMS processing failed for %s", document_id)
            await db.execute(
                text("UPDATE documents SET processing_status = 'failed' WHERE id = :id"),
                {"id": str(document_id)},
            )
            await db.commit()


async def _run_processing(db: AsyncSession, document_id: uuid.UUID) -> None:

    result = await db.execute(
        text("SELECT id, file_url, mime_type, name, tenant_id FROM documents WHERE id = :id"),
        {"id": str(document_id)},
    )
    row = result.fetchone()
    if not row:
        return

    doc_id, file_url, mime_type, name, tenant_id = row

    # Download file bytes
    file_bytes = await _download_bytes(file_url, tenant_id)
    if not file_bytes:
        await db.execute(
            text("UPDATE documents SET processing_status = 'failed' WHERE id = :id"),
            {"id": str(doc_id)},
        )
        await db.commit()
        return

    ocr_text: str = ""
    thumbnail_url: str | None = None

    if mime_type == "application/pdf":
        ocr_text = _extract_pdf_text(file_bytes)
        thumbnail_url = await _generate_pdf_thumbnail(file_bytes, doc_id)
    elif mime_type.startswith("image/"):
        ocr_text = _extract_image_text(file_bytes)
        thumbnail_url = await _generate_image_thumbnail(file_bytes, doc_id, mime_type)

    # Build tsvector
    ts_input = f"{name} {ocr_text}"[:100_000]  # limit to 100k chars

    await db.execute(
        text("""
            UPDATE documents SET
                ocr_text = :ocr,
                thumbnail_url = :thumb,
                processing_status = 'done',
                search_vector = to_tsvector('german', :ts),
                updated_at = :now
            WHERE id = :id
            """),
        {
            "ocr": ocr_text or None,
            "thumb": thumbnail_url,
            "ts": ts_input,
            "now": datetime.now(UTC),
            "id": str(doc_id),
        },
    )
    await db.commit()
    logger.info("DMS processing done for %s", doc_id)


async def _download_bytes(url: str, tenant_id: uuid.UUID) -> bytes | None:
    from app.dms.download import download_document

    try:
        return await download_document(url, tenant_id)
    except (httpx.HTTPError, ValueError):
        logger.warning("Document download rejected or unavailable")
        return None


def _extract_pdf_text(data: bytes) -> str:
    """Extract text from PDF using pypdf."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        parts: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            parts.append(text)
        return "\n".join(parts).strip()
    except Exception:
        logger.exception("pypdf extraction failed")
        return ""


def _extract_image_text(data: bytes) -> str:
    """Extract text from image using pytesseract (OCR)."""
    try:
        import pytesseract
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        return str(pytesseract.image_to_string(img, lang="deu+eng")).strip()
    except Exception:
        logger.exception("pytesseract OCR failed")
        return ""


async def _generate_pdf_thumbnail(data: bytes, doc_id: uuid.UUID) -> str | None:
    """Convert first page of PDF to PNG thumbnail, upload to S3."""
    try:
        from pdf2image import convert_from_bytes

        pages = convert_from_bytes(data, first_page=1, last_page=1, dpi=72)
        if not pages:
            return None
        img = pages[0]
        img.thumbnail((_THUMB_MAX_WIDTH, _THUMB_MAX_HEIGHT))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return await _upload_thumbnail(buf.read(), doc_id, "image/png")
    except Exception:
        logger.exception("PDF thumbnail generation failed")
        return None


async def _generate_image_thumbnail(data: bytes, doc_id: uuid.UUID, mime_type: str) -> str | None:
    """Resize image to thumbnail size, upload to S3."""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        img.thumbnail((_THUMB_MAX_WIDTH, _THUMB_MAX_HEIGHT))
        buf = io.BytesIO()
        fmt = "JPEG" if mime_type == "image/jpeg" else "PNG"
        img.save(buf, format=fmt, optimize=True)
        buf.seek(0)
        return await _upload_thumbnail(buf.read(), doc_id, f"image/{fmt.lower()}")
    except Exception:
        logger.exception("Image thumbnail generation failed")
        return None


async def _upload_thumbnail(data: bytes, doc_id: uuid.UUID, content_type: str) -> str | None:
    """Upload thumbnail bytes to S3 and return public URL. Returns None if S3 not configured."""
    try:
        import asyncio

        from app.config import get_settings
        from app.storage.s3 import _get_s3_client

        s = get_settings()
        key = f"thumbnails/{doc_id}.png"

        def _put() -> None:
            client = _get_s3_client()
            client.put_object(
                Bucket=s.s3_bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )

        await asyncio.to_thread(_put)

        base = (
            s.s3_public_url_base.rstrip("/")
            if s.s3_public_url_base
            else f"https://{s.s3_bucket}.s3.amazonaws.com"
        )
        return f"{base}/{key}"
    except Exception:
        # S3 not configured or upload failed — thumbnail optional, don't fail processing
        return None


async def update_search_vector(db: AsyncSession, document_id: uuid.UUID, text_content: str) -> None:
    """Re-run tsvector update for an existing document (e.g. after metadata edit)."""
    await db.execute(
        text("UPDATE documents SET search_vector = to_tsvector('german', :ts) WHERE id = :id"),
        {"ts": text_content[:100_000], "id": str(document_id)},
    )
