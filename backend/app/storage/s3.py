"""S3 / Cloudflare R2 storage helper (Sprint 2.8).

Provides presigned PUT URLs for direct browser-to-storage uploads.
Works with any S3-compatible storage (AWS S3, Cloudflare R2, MinIO).

When S3 is not configured (dev/test), raises StorageNotConfigured so
callers can handle gracefully.
"""

from __future__ import annotations

import asyncio
import mimetypes
import uuid as _uuid
from typing import Any, Protocol, cast

_ALLOWED_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
    "image/svg+xml",
}

_MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


class StorageNotConfigured(Exception):
    """Raised when S3/R2 credentials are missing."""


class S3Client(Protocol):
    def generate_presigned_url(self, method: str, **kwargs: Any) -> str: ...
    def put_object(self, **kwargs: Any) -> Any: ...


def _get_s3_client() -> S3Client:
    """Create a boto3 S3 client from settings. Raises StorageNotConfigured if unconfigured."""
    try:
        import boto3
    except ImportError as exc:
        raise StorageNotConfigured("boto3 not installed") from exc

    from app.config import get_settings

    s = get_settings()

    if not s.s3_access_key or not s.s3_secret_key or not s.s3_bucket:
        raise StorageNotConfigured("S3 credentials not configured")

    kwargs: dict[str, Any] = {
        "aws_access_key_id": s.s3_access_key,
        "aws_secret_access_key": s.s3_secret_key,
    }
    if s.s3_endpoint_url:
        kwargs["endpoint_url"] = s.s3_endpoint_url

    return cast(S3Client, boto3.client("s3", **kwargs))


def _presign_sync(key: str, content_type: str, expires: int) -> str:
    """Generate a presigned PUT URL (synchronous, run in thread)."""
    from app.config import get_settings

    client = _get_s3_client()
    bucket = get_settings().s3_bucket
    return client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ContentType": content_type,
            "ContentLength": _MAX_FILE_SIZE,
        },
        ExpiresIn=expires,
        HttpMethod="PUT",
    )


async def generate_presigned_upload(
    tenant_id: str,
    filename: str,
    content_type: str,
    expires: int = 300,  # 5 minutes
) -> tuple[str, str]:
    """Return (upload_url, public_url) for a direct browser upload.

    Raises StorageNotConfigured if S3 is not configured.
    Raises ValueError if the content type is not allowed.
    """
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise ValueError(f"Nicht erlaubter Dateityp: {content_type}")

    ext = mimetypes.guess_extension(content_type) or ".png"
    if ext == ".jpe":
        ext = ".jpg"
    key = f"logos/{tenant_id}/{_uuid.uuid4().hex}{ext}"

    upload_url = await asyncio.to_thread(_presign_sync, key, content_type, expires)

    from app.config import get_settings

    s = get_settings()
    base = (
        s.s3_public_url_base.rstrip("/")
        if s.s3_public_url_base
        else f"https://{s.s3_bucket}.s3.amazonaws.com"
    )
    public_url = f"{base}/{key}"

    return upload_url, public_url
