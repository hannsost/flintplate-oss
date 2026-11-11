"""No real network access: storage boundary and bounded download checks."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.dms.download import download_document, validate_storage_url

TENANT = uuid.uuid4()
BASE = "https://assets.example.com"
VALID = f"{BASE}/documents/{TENANT}/synthetic.pdf"


@pytest.fixture(autouse=True)
def storage_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.dms.download.get_settings",
        lambda: SimpleNamespace(s3_public_url_base=BASE, s3_bucket=None),
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/private",
        "http://169.254.169.254/latest/meta-data",
        "file:///etc/passwd",
        f"{BASE}/documents/{uuid.uuid4()}/private.pdf",
        VALID.replace("assets.example.com", "assets.example.com.evil.test"),
        VALID.replace("assets.example.com", "user@assets.example.com"),
        VALID.replace("synthetic.pdf", "../private.pdf"),
        VALID.replace("synthetic.pdf", "%2e%2e/private.pdf"),
        VALID.replace("synthetic.pdf", "%252e%252e/private.pdf"),
    ],
)
def test_untrusted_document_sources_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        validate_storage_url(url, TENANT)


async def test_configured_document_download(monkeypatch: pytest.MonkeyPatch) -> None:
    original = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"Synthetic PDF bytes")
    )
    monkeypatch.setattr(
        "app.dms.download.httpx.AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )
    assert await download_document(VALID, TENANT) == b"Synthetic PDF bytes"


async def test_download_does_not_follow_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    original = httpx.AsyncClient
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url)
        return httpx.Response(302, headers={"location": "http://169.254.169.254/private"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.dms.download.httpx.AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await download_document(VALID, TENANT)
    assert len(requests) == 1


async def test_download_size_limit_applies_to_streamed_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=b"too many bytes", headers={"content-length": "0"}
        )
    )
    monkeypatch.setattr("app.dms.download.MAX_DOCUMENT_BYTES", 5)
    monkeypatch.setattr(
        "app.dms.download.httpx.AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )
    with pytest.raises(ValueError):
        await download_document(VALID, TENANT)
