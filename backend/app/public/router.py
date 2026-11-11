"""Public / unauthenticated endpoints for white-label / custom-domain support.

GET /public/branding?domain=...    – resolve tenant branding by custom domain
GET /public/branding/slug/{slug}   – resolve tenant branding by slug (preview)
GET /public/jobs?slug=...          – public job listings for a tenant
GET /public/jobs/{job_id}          – single public job detail
"""

from __future__ import annotations

import uuid
from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.database import get_db
from app.jobs.models import JobPosting
from app.jobs.publication import public_job_condition
from app.jobs.schemas import JobPostingRead

router = APIRouter()


class TenantBranding(BaseModel):
    name: str
    slug: str
    plan: str
    status: str
    custom_domain: str | None
    primary_color: str  # defaults to "#2563eb" (palmscout blue)
    logo_url: str | None


def _branding(c: Customer) -> TenantBranding:
    return TenantBranding(
        name=c.brand_name or c.name,
        slug=c.slug,
        plan=c.plan,
        status=c.status,
        custom_domain=c.custom_domain,
        primary_color=c.primary_color or "#2563eb",
        logo_url=c.logo_url,
    )


@router.get("/branding", response_model=TenantBranding, summary="Tenant-Branding per Custom-Domain")
async def get_branding_by_domain(
    domain: str = Query(..., description="Custom domain to look up, e.g. 'recruit.acme.de'"),
    db: AsyncSession = Depends(get_db),
) -> TenantBranding:
    result = await db.execute(
        select(Customer).where(
            Customer.custom_domain == domain.lower().strip(),
            Customer.status.not_in(["churned", "suspended"]),
        )
    )
    c = result.scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="Kein Tenant für diese Domain gefunden")
    return _branding(c)


@router.get(
    "/branding/slug/{slug}", response_model=TenantBranding, summary="Tenant-Branding per Slug"
)
async def get_branding_by_slug(
    slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TenantBranding:
    result = await db.execute(
        select(Customer).where(
            Customer.slug == slug,
            Customer.status.not_in(["churned", "suspended"]),
        )
    )
    c = result.scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="Tenant nicht gefunden")
    return _branding(c)


async def _resolve_tenant_by_slug(slug: str, db: AsyncSession) -> Customer:
    result = await db.execute(
        select(Customer).where(
            Customer.slug == slug,
            Customer.status.not_in(["churned", "suspended"]),
        )
    )
    c = result.scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="Tenant nicht gefunden")
    return c


@router.get(
    "/jobs", response_model=list[JobPostingRead], summary="Öffentliche Job-Liste eines Tenants"
)
async def get_public_jobs(
    slug: str = Query(..., description="Tenant-Slug"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[JobPostingRead]:
    customer = await _resolve_tenant_by_slug(slug, db)
    result = await db.execute(
        select(JobPosting)
        .where(JobPosting.tenant_id == customer.id, public_job_condition())
        .order_by(JobPosting.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [JobPostingRead.model_validate(job) for job in result.scalars()]


@router.get("/jobs/{job_id}", response_model=JobPostingRead, summary="Öffentliche Job-Detailseite")
async def get_public_job(
    job_id: uuid.UUID,
    slug: str | None = Query(None, max_length=100),
    db: AsyncSession = Depends(get_db),
) -> JobPostingRead:
    query = (
        select(JobPosting)
        .join(Customer, Customer.id == JobPosting.tenant_id)
        .where(JobPosting.id == job_id, public_job_condition())
    )
    if slug is not None:
        query = query.where(Customer.slug == slug)
    result = await db.execute(query)
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Stelle nicht gefunden")
    return JobPostingRead.model_validate(job)


# ── Public document share view ────────────────────────────────────────────────


class PublicDocumentRead(BaseModel):
    id: uuid.UUID
    name: str
    original_filename: str
    file_url: str
    mime_type: str
    file_size: int
    description: str | None
    thumbnail_url: str | None
    access_type: str


@router.get(
    "/documents/{token}",
    response_model=PublicDocumentRead,
    summary="Geteiltes Dokument per Token abrufen",
)
async def get_shared_document(
    token: str,
    password: str | None = Query(None, description="Passwort falls geschützt"),
    db: AsyncSession = Depends(get_db),
) -> PublicDocumentRead:
    """Resolve a share token and return limited document metadata + file_url."""
    from datetime import datetime

    from app.dms.models import DocShare, Document

    result = await db.execute(select(DocShare).where(DocShare.share_token == token))
    share = result.scalar_one_or_none()
    if not share:
        raise HTTPException(status_code=404, detail="Link ungültig oder abgelaufen")

    now = datetime.now(UTC)
    if share.expires_at and share.expires_at < now:
        raise HTTPException(status_code=410, detail="Dieser Link ist abgelaufen")

    if share.password_hash:
        if not password:
            raise HTTPException(status_code=401, detail="Passwort erforderlich")
        try:
            from passlib.hash import bcrypt as pw_bcrypt

            if not pw_bcrypt.verify(password, share.password_hash):
                raise HTTPException(status_code=403, detail="Falsches Passwort")
        except Exception:
            raise HTTPException(status_code=403, detail="Falsches Passwort") from None

    doc_result = await db.execute(select(Document).where(Document.id == share.document_id))
    doc = doc_result.scalar_one_or_none()
    if not doc or doc.status != "active":
        raise HTTPException(status_code=404, detail="Dokument nicht mehr verfügbar")

    # Track access
    share.accessed_count += 1
    share.last_accessed_at = now
    await db.commit()

    return PublicDocumentRead(
        id=doc.id,
        name=doc.name,
        original_filename=doc.original_filename,
        file_url=doc.file_url,
        mime_type=doc.mime_type,
        file_size=doc.file_size,
        description=doc.description,
        thumbnail_url=doc.thumbnail_url,
        access_type=share.access_type,
    )
