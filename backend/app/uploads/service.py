"""File upload service – local storage for Phase 0, S3-ready for Phase 1."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

# ── Config ────────────────────────────────────────────────────────────────────
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "uploads"))
MAX_FILE_SIZE_MB = 10
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx"}


def _ensure_upload_dir(user_id: uuid.UUID) -> Path:
    path = UPLOAD_DIR / str(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _validate_file(file: UploadFile) -> None:
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Dateityp '{file.content_type}' nicht erlaubt. Erlaubt: PDF, DOC, DOCX",
        )
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Dateiendung '{suffix}' nicht erlaubt.",
        )


async def save_cv(file: UploadFile, user_id: uuid.UUID) -> tuple[str, str]:
    """Save uploaded CV to local disk.

    Returns:
        (file_path, original_filename)

    Phase 1 upgrade: replace body with S3 PutObject call.
    """
    _validate_file(file)

    content = await file.read()
    if len(content) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Datei zu groß. Maximum: {MAX_FILE_SIZE_MB} MB",
        )

    upload_dir = _ensure_upload_dir(user_id)
    suffix = Path(file.filename or "cv").suffix.lower() or ".pdf"
    filename = f"{uuid.uuid4().hex}{suffix}"
    file_path = upload_dir / filename

    file_path.write_bytes(content)

    return str(file_path), file.filename or filename


async def delete_cv(file_path: str) -> None:
    """Remove a previously saved CV file."""
    path = Path(file_path)
    if path.exists():
        path.unlink()
