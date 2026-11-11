"""DMS API router (Sprint 3.1).

Endpoints:
  POST   /documents/presign              → get S3 presigned upload URL
  POST   /documents                      → register uploaded document
  GET    /documents                      → list (search, filter, paginate)
  GET    /documents/{id}                 → document detail + shares + activity + comments
  PATCH  /documents/{id}                 → update metadata
  DELETE /documents/{id}                 → soft-delete (status=deleted)
  POST   /documents/{id}/archive         → archive
  POST   /documents/{id}/restore         → restore to active
  POST   /documents/{id}/new-version     → create new version
  GET    /documents/{id}/versions        → version history

  POST   /documents/{id}/shares          → create share link
  GET    /documents/{id}/shares          → list share links
  DELETE /documents/{id}/shares/{sid}    → revoke share link

  GET    /documents/{id}/activity        → audit log
  GET    /documents/{id}/comments        → list comments
  POST   /documents/{id}/comments        → add comment
  DELETE /documents/{id}/comments/{cid} → delete comment

  GET    /documents/expiry               → expiry dashboard (overdue/soon/ok)
  POST   /documents/bulk-download        → ZIP of multiple documents (streaming)

  GET    /categories                     → global + tenant categories
  POST   /categories                     → create tenant category
  PATCH  /categories/{id}               → update
  DELETE /categories/{id}               → delete (tenant-only)
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import uuid
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from passlib.hash import bcrypt
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import TenantDB, TenantRecruiterUser
from app.dms.models import DocActivity, DocCategory, DocComment, DocShare, Document
from app.dms.schemas import (
    BulkDownloadRequest,
    DocActivityRead,
    DocCategoryCreate,
    DocCategoryRead,
    DocCategoryUpdate,
    DocCommentCreate,
    DocCommentRead,
    DocShareCreate,
    DocShareRead,
    DocumentCreate,
    DocumentDetail,
    DocumentPresignRequest,
    DocumentPresignResponse,
    DocumentRead,
    DocumentUpdate,
    ExpiryDashboard,
)

router = APIRouter()


# ── helpers ───────────────────────────────────────────────────────────────────


def _doc_to_read(doc: Document, category: DocCategory | None = None) -> DocumentRead:
    r = DocumentRead.model_validate(doc)
    if category:
        r.category = DocCategoryRead.model_validate(category)
    return r


async def _get_doc_or_404(db: AsyncSession, doc_id: uuid.UUID, tenant_id: uuid.UUID) -> Document:
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.tenant_id == tenant_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    return doc


async def _log(
    db: AsyncSession,
    document_id: uuid.UUID,
    user_id: uuid.UUID | None,
    action: str,
    meta: dict[str, Any] | None = None,
) -> None:
    activity = DocActivity(
        id=uuid.uuid4(),
        document_id=document_id,
        user_id=user_id,
        action=action,
        metadata_=meta,
    )
    db.add(activity)


async def _validate_references(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    category_id: uuid.UUID | None,
    linked_type: str | None = None,
    linked_id: uuid.UUID | None = None,
) -> None:
    if category_id:
        category = await db.get(DocCategory, category_id)
        if category is None or category.tenant_id not in {None, tenant_id}:
            raise HTTPException(status_code=404, detail="Kategorie nicht gefunden.")
    if linked_type == "worker":
        from app.worker.access import require_member

        if linked_id is None:
            raise HTTPException(
                status_code=422, detail="Eine Mitarbeiterzuordnung erfordert eine Person."
            )
        await require_member(db, tenant_id, linked_id)


async def _root_document(db: AsyncSession, doc: Document) -> Document:
    seen: set[uuid.UUID] = set()
    while doc.parent_document_id is not None:
        if doc.id in seen:
            raise HTTPException(status_code=409, detail="Ungültige Versionskette.")
        seen.add(doc.id)
        doc = await _get_doc_or_404(db, doc.parent_document_id, doc.tenant_id)
    return doc


async def _versions(db: AsyncSession, doc: Document) -> list[Document]:
    root = await _root_document(db, doc)
    lineage = select(Document.id).where(Document.id == root.id).cte(recursive=True)
    lineage = lineage.union_all(
        select(Document.id)
        .join(lineage, Document.parent_document_id == lineage.c.id)
        .where(Document.tenant_id == doc.tenant_id)
    )
    result = await db.execute(
        select(Document)
        .join(lineage, Document.id == lineage.c.id)
        .order_by(Document.version_number.asc())
        .execution_options(populate_existing=True)
    )
    return list(result.scalars().all())


# ── presign ───────────────────────────────────────────────────────────────────

_ALLOWED_MIME = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
}
_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


@router.post("/presign", response_model=DocumentPresignResponse)
async def presign_upload(
    body: DocumentPresignRequest,
    user: TenantRecruiterUser,
) -> DocumentPresignResponse:
    """Generate an S3 presigned PUT URL for direct browser upload."""
    if body.mime_type not in _ALLOWED_MIME:
        raise HTTPException(status_code=400, detail=f"Dateityp nicht erlaubt: {body.mime_type}")
    if body.file_size > _MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Datei zu groß (max 50 MB)")

    try:
        import asyncio

        from app.config import get_settings
        from app.storage.s3 import _get_s3_client

        s = get_settings()
        ext = body.filename.rsplit(".", 1)[-1] if "." in body.filename else "bin"
        key = f"documents/{user.tenant_id}/{uuid.uuid4().hex}.{ext}"

        def _presign() -> str:
            client = _get_s3_client()
            return client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": s.s3_bucket,
                    "Key": key,
                    "ContentType": body.mime_type,
                    "ContentLength": body.file_size,
                },
                ExpiresIn=600,
                HttpMethod="PUT",
            )

        upload_url = await asyncio.to_thread(_presign)
        base = (
            s.s3_public_url_base.rstrip("/")
            if s.s3_public_url_base
            else f"https://{s.s3_bucket}.s3.amazonaws.com"
        )
        file_url = f"{base}/{key}"

    except Exception:
        # S3 not configured — return placeholder so frontend can still use direct URL input
        raise HTTPException(
            status_code=503,
            detail="S3 nicht konfiguriert. Bitte Datei-URL manuell eintragen.",
        ) from None

    return DocumentPresignResponse(
        upload_url=upload_url,
        file_url=file_url,
        original_filename=body.filename,
        mime_type=body.mime_type,
        file_size=body.file_size,
    )


# ── CRUD ──────────────────────────────────────────────────────────────────────


@router.post("", response_model=DocumentRead, status_code=201)
async def create_document(
    body: DocumentCreate,
    user: TenantRecruiterUser,
    db: TenantDB,
) -> DocumentRead:
    await _validate_references(
        db, user.tenant_id, body.category_id, body.linked_entity_type, body.linked_entity_id
    )
    doc = Document(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        created_by=user.id,
        **body.model_dump(),
    )
    db.add(doc)
    await db.flush()
    await _log(db, doc.id, user.id, "uploaded", {"filename": body.original_filename})
    await db.commit()
    await db.refresh(doc)

    # Kick off background OCR + thumbnail (non-blocking)
    asyncio.ensure_future(_safe_process(doc.id))

    return _doc_to_read(doc)


async def _safe_process(doc_id: uuid.UUID) -> None:
    from app.dms.service import process_document

    with contextlib.suppress(Exception):
        await process_document(doc_id)


@router.get("", response_model=list[DocumentRead])
async def list_documents(
    user: TenantRecruiterUser,
    db: TenantDB,
    q: str | None = Query(None, description="Full-text search query"),
    category_id: uuid.UUID | None = Query(None),
    status: str = Query("active"),
    linked_entity_type: str | None = Query(None),
    linked_entity_id: uuid.UUID | None = Query(None),
    is_template: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[DocumentRead]:
    stmt = select(Document).where(
        Document.tenant_id == user.tenant_id,
        Document.status == status,
        Document.is_latest_version == True,  # noqa: E712
    )

    if category_id:
        stmt = stmt.where(Document.category_id == category_id)
    if linked_entity_type:
        stmt = stmt.where(Document.linked_entity_type == linked_entity_type)
    if linked_entity_id:
        stmt = stmt.where(Document.linked_entity_id == linked_entity_id)
    if is_template is not None:
        stmt = stmt.where(Document.is_template == is_template)
    if q:
        # full-text if search_vector populated, fallback to ILIKE on name
        stmt = stmt.where(
            or_(
                Document.search_vector.op("@@")(func.plainto_tsquery("german", q)),
                Document.name.ilike(f"%{q}%"),
            )
        )

    stmt = stmt.order_by(Document.updated_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    docs = result.scalars().all()

    # Fetch categories in one query
    cat_ids = {d.category_id for d in docs if d.category_id}
    cats: dict[uuid.UUID, DocCategory] = {}
    if cat_ids:
        cat_result = await db.execute(select(DocCategory).where(DocCategory.id.in_(cat_ids)))
        for c in cat_result.scalars().all():
            cats[c.id] = c

    return [_doc_to_read(d, cats.get(d.category_id) if d.category_id else None) for d in docs]


@router.get("/expiry", response_model=ExpiryDashboard)
async def expiry_dashboard(
    user: TenantRecruiterUser,
    db: TenantDB,
) -> ExpiryDashboard:
    now = datetime.now(UTC)
    from datetime import timedelta

    soon = now + timedelta(days=30)

    result = await db.execute(
        select(Document)
        .where(
            Document.tenant_id == user.tenant_id,
            Document.status == "active",
            Document.expires_at.isnot(None),
        )
        .order_by(Document.expires_at.asc())
    )
    docs = result.scalars().all()

    overdue = [_doc_to_read(d) for d in docs if d.expires_at and d.expires_at < now]
    expiring_soon = [_doc_to_read(d) for d in docs if d.expires_at and now <= d.expires_at <= soon]
    ok = [_doc_to_read(d) for d in docs if d.expires_at and d.expires_at > soon]

    return ExpiryDashboard(overdue=overdue, expiring_soon=expiring_soon, ok=ok)


@router.get("/{doc_id}", response_model=DocumentDetail)
async def get_document(
    doc_id: uuid.UUID,
    user: TenantRecruiterUser,
    db: TenantDB,
) -> DocumentDetail:
    doc = await _get_doc_or_404(db, doc_id, user.tenant_id)

    # Shares
    shares_result = await db.execute(
        select(DocShare).where(DocShare.document_id == doc_id).order_by(DocShare.created_at.desc())
    )
    shares = [DocShareRead.model_validate(s) for s in shares_result.scalars().all()]

    # Activity
    act_result = await db.execute(
        select(DocActivity)
        .where(DocActivity.document_id == doc_id)
        .order_by(DocActivity.created_at.desc())
        .limit(100)
    )
    activity = [DocActivityRead.model_validate(a) for a in act_result.scalars().all()]

    # Comments
    comments_result = await db.execute(
        select(DocComment)
        .where(DocComment.document_id == doc_id)
        .order_by(DocComment.created_at.asc())
    )
    comments = [DocCommentRead.model_validate(c) for c in comments_result.scalars().all()]

    versions = [_doc_to_read(v) for v in await _versions(db, doc)]

    # Category
    category: DocCategory | None = None
    if doc.category_id:
        cat_res = await db.get(DocCategory, doc.category_id)
        category = cat_res

    await _log(db, doc_id, user.id, "viewed")
    await db.commit()

    detail = DocumentDetail.model_validate(doc)
    detail.category = DocCategoryRead.model_validate(category) if category else None
    detail.shares = shares
    detail.activity = activity
    detail.comments = comments
    detail.versions = versions
    return detail


@router.patch("/{doc_id}", response_model=DocumentRead)
async def update_document(
    doc_id: uuid.UUID,
    body: DocumentUpdate,
    user: TenantRecruiterUser,
    db: TenantDB,
) -> DocumentRead:
    doc = await _get_doc_or_404(db, doc_id, user.tenant_id)

    await _validate_references(db, user.tenant_id, body.category_id)
    update_data = body.model_dump(exclude_none=True)
    for k, v in update_data.items():
        setattr(doc, k, v)
    doc.updated_at = datetime.now(UTC)

    await _log(db, doc_id, user.id, "edited", body.model_dump(mode="json", exclude_none=True))
    await db.commit()
    await db.refresh(doc)

    # Re-index search vector with new name/description if changed
    if "name" in update_data or "description" in update_data:
        ts = f"{doc.name} {doc.description or ''} {doc.ocr_text or ''}"
        from app.dms.service import update_search_vector

        await update_search_vector(db, doc_id, ts)
        await db.commit()

    return _doc_to_read(doc)


@router.delete("/{doc_id}", status_code=204)
async def delete_document(
    doc_id: uuid.UUID,
    user: TenantRecruiterUser,
    db: TenantDB,
) -> None:
    doc = await _get_doc_or_404(db, doc_id, user.tenant_id)
    doc.status = "deleted"
    doc.updated_at = datetime.now(UTC)
    await _log(db, doc_id, user.id, "deleted")
    await db.commit()


@router.post("/{doc_id}/archive", response_model=DocumentRead)
async def archive_document(
    doc_id: uuid.UUID,
    user: TenantRecruiterUser,
    db: TenantDB,
) -> DocumentRead:
    doc = await _get_doc_or_404(db, doc_id, user.tenant_id)
    doc.status = "archived"
    doc.archived_at = datetime.now(UTC)
    doc.updated_at = datetime.now(UTC)
    await _log(db, doc_id, user.id, "archived")
    await db.commit()
    await db.refresh(doc)
    return _doc_to_read(doc)


@router.post("/{doc_id}/restore", response_model=DocumentRead)
async def restore_document(
    doc_id: uuid.UUID,
    user: TenantRecruiterUser,
    db: TenantDB,
) -> DocumentRead:
    doc = await _get_doc_or_404(db, doc_id, user.tenant_id)
    doc.status = "active"
    doc.archived_at = None
    doc.updated_at = datetime.now(UTC)
    await _log(db, doc_id, user.id, "restored")
    await db.commit()
    await db.refresh(doc)
    return _doc_to_read(doc)


@router.post("/{doc_id}/new-version", response_model=DocumentRead, status_code=201)
async def create_new_version(
    doc_id: uuid.UUID,
    body: DocumentCreate,
    user: TenantRecruiterUser,
    db: TenantDB,
) -> DocumentRead:
    parent = await _get_doc_or_404(db, doc_id, user.tenant_id)

    await _validate_references(
        db, user.tenant_id, body.category_id, body.linked_entity_type, body.linked_entity_id
    )
    root = await _root_document(db, parent)
    # Lock the root so concurrent uploads cannot create competing latest versions.
    await db.execute(select(Document.id).where(Document.id == root.id).with_for_update())
    versions = await _versions(db, root)
    next_version = max(v.version_number for v in versions) + 1
    for version in versions:
        version.is_latest_version = False
        version.updated_at = datetime.now(UTC)

    new_doc = Document(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        created_by=user.id,
        parent_document_id=root.id,
        version_number=next_version,
        is_latest_version=True,
        **body.model_dump(),
    )
    db.add(new_doc)
    await db.flush()
    await _log(
        db,
        new_doc.id,
        user.id,
        "new_version",
        {"from": str(parent.id), "version": new_doc.version_number},
    )
    await db.commit()
    await db.refresh(new_doc)

    asyncio.ensure_future(_safe_process(new_doc.id))
    return _doc_to_read(new_doc)


@router.get("/{doc_id}/versions", response_model=list[DocumentRead])
async def list_versions(
    doc_id: uuid.UUID,
    user: TenantRecruiterUser,
    db: TenantDB,
) -> list[DocumentRead]:
    doc = await _get_doc_or_404(db, doc_id, user.tenant_id)
    return [_doc_to_read(d) for d in await _versions(db, doc)]


# ── Shares ────────────────────────────────────────────────────────────────────


@router.post("/{doc_id}/shares", response_model=DocShareRead, status_code=201)
async def create_share(
    doc_id: uuid.UUID,
    body: DocShareCreate,
    user: TenantRecruiterUser,
    db: TenantDB,
) -> DocShareRead:
    await _get_doc_or_404(db, doc_id, user.tenant_id)

    pw_hash: str | None = None
    if body.password:
        pw_hash = bcrypt.hash(body.password)

    share = DocShare(
        id=uuid.uuid4(),
        document_id=doc_id,
        shared_by=user.id,
        share_token=secrets.token_urlsafe(40),
        shared_with_email=body.shared_with_email,
        access_type=body.access_type,
        expires_at=body.expires_at,
        password_hash=pw_hash,
    )
    db.add(share)
    await _log(
        db, doc_id, user.id, "shared", {"email": body.shared_with_email, "access": body.access_type}
    )
    await db.commit()
    await db.refresh(share)
    return DocShareRead.model_validate(share)


@router.get("/{doc_id}/shares", response_model=list[DocShareRead])
async def list_shares(
    doc_id: uuid.UUID,
    user: TenantRecruiterUser,
    db: TenantDB,
) -> list[DocShareRead]:
    await _get_doc_or_404(db, doc_id, user.tenant_id)
    result = await db.execute(
        select(DocShare).where(DocShare.document_id == doc_id).order_by(DocShare.created_at.desc())
    )
    return [DocShareRead.model_validate(s) for s in result.scalars().all()]


@router.delete("/{doc_id}/shares/{share_id}", status_code=204)
async def revoke_share(
    doc_id: uuid.UUID,
    share_id: uuid.UUID,
    user: TenantRecruiterUser,
    db: TenantDB,
) -> None:
    await _get_doc_or_404(db, doc_id, user.tenant_id)
    result = await db.execute(
        select(DocShare).where(DocShare.id == share_id, DocShare.document_id == doc_id)
    )
    share = result.scalar_one_or_none()
    if not share:
        raise HTTPException(status_code=404, detail="Share nicht gefunden")
    await db.delete(share)
    await _log(db, doc_id, user.id, "share_revoked", {"share_id": str(share_id)})
    await db.commit()


# ── Activity ──────────────────────────────────────────────────────────────────


@router.get("/{doc_id}/activity", response_model=list[DocActivityRead])
async def get_activity(
    doc_id: uuid.UUID,
    user: TenantRecruiterUser,
    db: TenantDB,
    limit: int = Query(50, ge=1, le=200),
) -> list[DocActivityRead]:
    await _get_doc_or_404(db, doc_id, user.tenant_id)
    result = await db.execute(
        select(DocActivity)
        .where(DocActivity.document_id == doc_id)
        .order_by(DocActivity.created_at.desc())
        .limit(limit)
    )
    return [DocActivityRead.model_validate(a) for a in result.scalars().all()]


# ── Comments ──────────────────────────────────────────────────────────────────


@router.get("/{doc_id}/comments", response_model=list[DocCommentRead])
async def list_comments(
    doc_id: uuid.UUID,
    user: TenantRecruiterUser,
    db: TenantDB,
) -> list[DocCommentRead]:
    await _get_doc_or_404(db, doc_id, user.tenant_id)
    result = await db.execute(
        select(DocComment)
        .where(DocComment.document_id == doc_id)
        .order_by(DocComment.created_at.asc())
    )
    return [DocCommentRead.model_validate(c) for c in result.scalars().all()]


@router.post("/{doc_id}/comments", response_model=DocCommentRead, status_code=201)
async def add_comment(
    doc_id: uuid.UUID,
    body: DocCommentCreate,
    user: TenantRecruiterUser,
    db: TenantDB,
) -> DocCommentRead:
    await _get_doc_or_404(db, doc_id, user.tenant_id)
    comment = DocComment(
        id=uuid.uuid4(),
        document_id=doc_id,
        user_id=user.id,
        content=body.content,
    )
    db.add(comment)
    await _log(db, doc_id, user.id, "commented", {"preview": body.content[:80]})
    await db.commit()
    await db.refresh(comment)
    return DocCommentRead.model_validate(comment)


@router.delete("/{doc_id}/comments/{comment_id}", status_code=204)
async def delete_comment(
    doc_id: uuid.UUID,
    comment_id: uuid.UUID,
    user: TenantRecruiterUser,
    db: TenantDB,
) -> None:
    await _get_doc_or_404(db, doc_id, user.tenant_id)
    result = await db.execute(
        select(DocComment).where(
            DocComment.id == comment_id,
            DocComment.document_id == doc_id,
            DocComment.user_id == user.id,
        )
    )
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(
            status_code=404, detail="Kommentar nicht gefunden oder keine Berechtigung"
        )
    await db.delete(comment)
    await db.commit()


# ── Bulk download (streaming ZIP) ─────────────────────────────────────────────
# NOTE: registered before /{doc_id} in main.py via bulk_router

bulk_router = APIRouter()


@bulk_router.post("/bulk-download")
async def bulk_download(
    body: BulkDownloadRequest,
    user: TenantRecruiterUser,
    db: TenantDB,
) -> StreamingResponse:
    """Stream a ZIP archive containing all requested documents."""
    result = await db.execute(
        select(Document).where(
            Document.id.in_(body.document_ids),
            Document.tenant_id == user.tenant_id,
            Document.status == "active",
        )
    )
    docs = result.scalars().all()

    if not docs:
        raise HTTPException(status_code=404, detail="Keine Dokumente gefunden")

    from pathlib import PurePosixPath
    from tempfile import SpooledTemporaryFile

    from app.dms.download import download_document

    # Lifetime spans archive creation and response streaming; both failure and streaming close it.
    archive = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")  # noqa: SIM115
    total_size = 0
    names: set[str] = set()
    try:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for doc in docs:
                data = await download_document(doc.file_url, doc.tenant_id)
                total_size += len(data)
                if total_size > 100 * 1024 * 1024:
                    raise HTTPException(
                        status_code=413,
                        detail="Bitte weniger Dateien auswählen (maximal 100 MB je Download).",
                    )
                name = PurePosixPath(doc.original_filename.replace("\\", "/")).name
                if name in {"", ".", ".."} or name in names:
                    name = f"{doc.id}-{name.replace('.', '') or 'document'}"
                names.add(name)
                zf.writestr(name, data)
    except (httpx.HTTPError, ValueError) as exc:
        archive.close()
        raise HTTPException(
            status_code=503,
            detail="Die Dateien konnten nicht aus dem konfigurierten Dokumentenspeicher geladen werden.",
        ) from exc
    except BaseException:
        archive.close()
        raise
    archive.seek(0)

    async def _generate() -> AsyncIterator[bytes]:
        try:
            while chunk := archive.read(64 * 1024):
                yield chunk
        finally:
            archive.close()

    return StreamingResponse(
        _generate(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="dokumente.zip"'},
    )


# ── Categories (separate router — avoid /{doc_id} conflict) ──────────────────

categories_router = APIRouter()


@categories_router.get("", response_model=list[DocCategoryRead])
async def list_categories(
    user: TenantRecruiterUser,
    db: TenantDB,
) -> list[DocCategoryRead]:
    result = await db.execute(
        select(DocCategory)
        .where(or_(DocCategory.tenant_id.is_(None), DocCategory.tenant_id == user.tenant_id))
        .order_by(DocCategory.sort_order.asc(), DocCategory.name.asc())
    )
    return [DocCategoryRead.model_validate(c) for c in result.scalars().all()]


@categories_router.post("", response_model=DocCategoryRead, status_code=201)
async def create_category(
    body: DocCategoryCreate,
    user: TenantRecruiterUser,
    db: TenantDB,
) -> DocCategoryRead:
    cat = DocCategory(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        is_system=False,
        **body.model_dump(),
    )
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return DocCategoryRead.model_validate(cat)


@categories_router.patch("/{cat_id}", response_model=DocCategoryRead)
async def update_category(
    cat_id: uuid.UUID,
    body: DocCategoryUpdate,
    user: TenantRecruiterUser,
    db: TenantDB,
) -> DocCategoryRead:
    result = await db.execute(
        select(DocCategory).where(DocCategory.id == cat_id, DocCategory.tenant_id == user.tenant_id)
    )
    cat = result.scalar_one_or_none()
    if not cat:
        raise HTTPException(status_code=404, detail="Kategorie nicht gefunden")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(cat, k, v)
    await db.commit()
    await db.refresh(cat)
    return DocCategoryRead.model_validate(cat)


@categories_router.delete("/{cat_id}", status_code=204)
async def delete_category(
    cat_id: uuid.UUID,
    user: TenantRecruiterUser,
    db: TenantDB,
) -> None:
    result = await db.execute(
        select(DocCategory).where(DocCategory.id == cat_id, DocCategory.tenant_id == user.tenant_id)
    )
    cat = result.scalar_one_or_none()
    if not cat:
        raise HTTPException(
            status_code=404, detail="Kategorie nicht gefunden oder keine Berechtigung"
        )
    if cat.is_system:
        raise HTTPException(
            status_code=400, detail="System-Kategorien können nicht gelöscht werden"
        )
    await db.delete(cat)
    await db.commit()
