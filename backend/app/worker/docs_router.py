"""Worker-facing document endpoints – /worker/documents (Sprint 4.7).

Workers can read their own documents (linked_entity_type='worker').
HR uploads documents via the DMS with linked_entity_type='worker' and
linked_entity_id=<worker_user_id>.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.dependencies import DBSession, WorkerUser
from app.dms.models import DocCategory, Document
from app.dms.schemas import DocCategoryRead, DocumentRead

router = APIRouter()


def _doc_to_read(doc: Document, category: DocCategory | None = None) -> DocumentRead:
    r = DocumentRead.model_validate(doc)
    if category:
        r.category = DocCategoryRead.model_validate(category)
    return r


@router.get("", response_model=list[DocumentRead])
async def list_my_documents(
    user: WorkerUser,
    db: DBSession,
    category_id: uuid.UUID | None = Query(None),
) -> list[DocumentRead]:
    from app.worker.models import WorkerSettings

    ws_row = await db.execute(select(WorkerSettings).where(WorkerSettings.user_id == user.id))
    ws = ws_row.scalar_one_or_none()
    if ws and not ws.active_modules.get("documents", True):
        raise HTTPException(status_code=403, detail="Dokumenten-Modul nicht aktiviert")

    stmt = select(Document).where(
        Document.tenant_id == user.tenant_id,
        Document.is_latest_version.is_(True),
        Document.linked_entity_type == "worker",
        Document.linked_entity_id == user.id,
        Document.status == "active",
    )
    if category_id:
        stmt = stmt.where(Document.category_id == category_id)

    stmt = stmt.order_by(Document.created_at.desc())
    rows = await db.execute(stmt)
    docs = list(rows.scalars().all())

    # batch-load categories
    cat_ids = {d.category_id for d in docs if d.category_id}
    cats: dict[uuid.UUID, DocCategory] = {}
    if cat_ids:
        c_rows = await db.execute(select(DocCategory).where(DocCategory.id.in_(cat_ids)))
        cats = {c.id: c for c in c_rows.scalars()}

    return [_doc_to_read(d, cats.get(d.category_id) if d.category_id else None) for d in docs]


@router.get("/{doc_id}", response_model=DocumentRead)
async def get_my_document(doc_id: uuid.UUID, user: WorkerUser, db: DBSession) -> DocumentRead:
    row = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.tenant_id == user.tenant_id,
            Document.is_latest_version.is_(True),
            Document.linked_entity_type == "worker",
            Document.linked_entity_id == user.id,
            Document.status == "active",
        )
    )
    doc = row.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")

    cat = None
    if doc.category_id:
        c_row = await db.execute(select(DocCategory).where(DocCategory.id == doc.category_id))
        cat = c_row.scalar_one_or_none()

    return _doc_to_read(doc, cat)
