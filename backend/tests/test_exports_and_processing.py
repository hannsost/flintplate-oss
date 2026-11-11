"""Real document generation, safe HTML handling and searchable document processing."""

from __future__ import annotations

import io
import uuid
from datetime import date
from unittest.mock import AsyncMock, Mock

import pytest
from docx import Document as DocxDocument
from httpx import AsyncClient
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dms import service
from app.dms.models import Document
from app.profiles.export import _build_cv_html, build_pdf
from app.profiles.models import CandidateProfile, Education, Skill, WorkExperience
from tests.hr_support import HRWorkspace, body


@pytest.fixture
async def complete_profile(db_session: AsyncSession, hr_workspace: HRWorkspace) -> CandidateProfile:
    profile = CandidateProfile(
        user_id=hr_workspace.worker.id,
        headline="Lagerlogistik",
        summary="Zuverlässig & erfahren",
        location="Berlin",
        phone="030 000000",
        linkedin_url="https://example.com/synthetic",
        skills=[Skill(name="Stapler", category="Logistik", level="advanced")],
        work_experiences=[
            WorkExperience(
                company="Synthetic Logistics",
                title="Fachkraft",
                location="Berlin",
                start_date=date(2020, 1, 1),
                is_current=True,
                description="Wareneingang geprüft",
            )
        ],
        educations=[
            Education(
                institution="Synthetic Schule",
                degree="Ausbildung",
                field_of_study="Logistik",
                start_date=date(2017, 1, 1),
                end_date=date(2019, 12, 31),
            )
        ],
    )
    db_session.add(profile)
    await db_session.flush()
    return profile


async def test_cv_exports_are_readable_and_do_not_execute_profile_markup(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    complete_profile: CandidateProfile,
) -> None:
    h = hr_workspace
    profile = complete_profile
    profile.summary = '<img src="file:///etc/hostname"> & Erfahrung'
    await db_session.flush()
    html = _build_cv_html(profile, h.worker)
    assert "<img src=" not in html and "&lt;img" in html
    pdf = await client.get("/profiles/me/export/pdf", headers=h.headers("worker"))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    text = " ".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "Lagerlogistik" in text and "Synthetic Logistics" in text
    docx = await client.get("/profiles/me/export/docx", headers=h.headers("worker"))
    assert docx.status_code == 200
    paragraphs = " ".join(p.text for p in DocxDocument(io.BytesIO(docx.content)).paragraphs)
    assert "Synthetic Logistics" in paragraphs and "Stapler" in paragraphs
    linkedin = body(await client.get("/profiles/me/export/linkedin", headers=h.headers("worker")))[
        "text"
    ]
    assert "Synthetic Schule" in linkedin and "2020" in linkedin


async def test_profile_link_requires_explicit_publication_and_can_be_revoked(
    client: AsyncClient,
    hr_workspace: HRWorkspace,
    complete_profile: CandidateProfile,
) -> None:
    h = hr_workspace
    public = f"/profiles/{complete_profile.id}"
    assert (await client.get(public)).status_code == 404
    body(await client.get("/profiles/me/export/link", headers=h.headers("worker")))
    assert (await client.get(public)).status_code == 404
    link = body(await client.post("/profiles/me/export/link", headers=h.headers("worker")))
    assert link["profile_id"] == str(complete_profile.id)
    assert body(await client.get(public))["headline"] == "Lagerlogistik"
    assert (
        await client.delete("/profiles/me/export/link", headers=h.headers("other_worker"))
    ).status_code == 204
    assert (await client.get(public)).status_code == 200
    assert (
        await client.delete("/profiles/me/export/link", headers=h.headers("worker"))
    ).status_code == 204
    assert (await client.get(public)).status_code == 404


@pytest.mark.parametrize("mime", ["application/pdf", "image/png", "image/jpeg"])
async def test_document_ocr_thumbnail_and_search(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    complete_profile: CandidateProfile,
    monkeypatch: pytest.MonkeyPatch,
    mime: str,
) -> None:
    h = hr_workspace
    if mime == "application/pdf":
        data = build_pdf(complete_profile, h.worker)
    else:
        bitmap = Image.new("RGB", (1200, 220), "white")
        draw = ImageDraw.Draw(bitmap)
        draw.text((40, 70), "Lagerlogistik", fill="black", font=ImageFont.load_default(size=65))
        stream = io.BytesIO()
        bitmap.save(stream, format="JPEG" if mime.endswith("jpeg") else "PNG")
        data = stream.getvalue()
    doc = Document(
        tenant_id=h.hr.tenant_id,
        created_by=h.hr.id,
        name="Nachweis",
        original_filename="proof",
        file_url="https://files.example.com/synthetic",
        mime_type=mime,
    )
    db_session.add(doc)
    await db_session.flush()
    download = AsyncMock(return_value=data)
    store = Mock()
    monkeypatch.setattr(service, "_download_bytes", download)
    monkeypatch.setattr("app.storage.s3._get_s3_client", lambda: store)
    await service._run_processing(db_session, doc.id)
    await db_session.refresh(doc)
    assert doc.processing_status == "done"
    assert doc.ocr_text and "Lagerlogistik" in doc.ocr_text
    assert doc.thumbnail_url and "/thumbnails/" in doc.thumbnail_url
    thumb = Image.open(io.BytesIO(store.put_object.call_args.kwargs["Body"]))
    assert thumb.width <= 400 and thumb.height <= 560
    search = body(await client.get("/documents?q=Lagerlogistik", headers=h.headers()))
    assert [d["id"] for d in search] == [str(doc.id)]
    await service.update_search_vector(db_session, doc.id, "Sonderqualifikation")
    matches = await db_session.execute(
        select(Document.id).where(
            Document.search_vector.op("@@")(func.plainto_tsquery("german", "Sonderqualifikation"))
        )
    )
    assert matches.scalar_one() == doc.id


async def test_document_unavailable_download_is_marked_failed(
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = Document(
        tenant_id=hr_workspace.hr.tenant_id,
        name="Unavailable",
        original_filename="missing.pdf",
        file_url="https://example.com/missing",
        mime_type="application/pdf",
    )
    db_session.add(doc)
    await db_session.flush()
    monkeypatch.setattr(service, "_download_bytes", AsyncMock(return_value=None))
    await service._run_processing(db_session, doc.id)
    await db_session.refresh(doc)
    assert doc.processing_status == "failed"
    await service._run_processing(db_session, uuid.uuid4())
