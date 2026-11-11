"""Bounded document downloads from the configured organization storage only."""

from __future__ import annotations

from urllib.parse import unquote, urlsplit
from uuid import UUID

import httpx

from app.config import get_settings

MAX_DOCUMENT_BYTES = 50 * 1024 * 1024


def validate_storage_url(url: str, tenant_id: UUID) -> None:
    settings = get_settings()
    base_url = settings.s3_public_url_base or (
        f"https://{settings.s3_bucket}.s3.amazonaws.com" if settings.s3_bucket else ""
    )
    if not base_url:
        raise ValueError("Dokumentenspeicher ist nicht konfiguriert.")
    base = urlsplit(base_url)
    target = urlsplit(url)
    path = unquote(target.path)
    prefix = f"{base.path.rstrip('/')}/documents/{tenant_id}/"
    if (
        target.scheme not in {"http", "https"}
        or target.scheme != base.scheme
        or target.netloc.lower() != base.netloc.lower()
        or target.username is not None
        or target.password is not None
        or target.fragment
        or not path.startswith(prefix)
        or not path[len(prefix) :]
        or "\\" in path
        or "%" in path
        or any(part in {".", ".."} for part in path.split("/"))
        or any(ord(c) < 32 for c in url)
    ):
        raise ValueError("Die Datei liegt nicht im Dokumentenspeicher dieser Organisation.")


async def download_document(url: str, tenant_id: UUID) -> bytes:
    validate_storage_url(url, tenant_id)
    # The host comes from trusted deployment configuration. Never follow redirects
    # from stored URLs to an unconfigured host or another organization's path.
    async with (
        httpx.AsyncClient(timeout=30, follow_redirects=False) as client,
        client.stream("GET", url) as response,
    ):
        response.raise_for_status()
        if int(response.headers.get("content-length", "0")) > MAX_DOCUMENT_BYTES:
            raise ValueError("Datei zu groß (maximal 50 MB).")
        data = bytearray()
        async for chunk in response.aiter_bytes():
            if len(data) + len(chunk) > MAX_DOCUMENT_BYTES:
                raise ValueError("Datei zu groß (maximal 50 MB).")
            data.extend(chunk)
    return bytes(data)
