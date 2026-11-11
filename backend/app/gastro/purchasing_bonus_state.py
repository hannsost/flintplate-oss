"""Current bonus document values are derived from immutable evidence."""

from __future__ import annotations

import hashlib
import json
import uuid

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.purchasing_bonus_models import (
    SupplierBonusAllocationReversal,
    SupplierBonusDocumentRevision,
)
from app.gastro.purchasing_terms_models import SupplierBonusAllocation, SupplierBonusDocument
from app.gastro.purchasing_terms_schemas import BonusDocumentRead


def allocation_digest(data: BaseModel) -> str:
    payload = data.model_dump(mode="json")
    # Existing V1 allocations and persisted browser payloads had no revision ID.
    if payload.get("document_revision_id") is None:
        payload.pop("document_revision_id", None)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def latest_revision(
    db: AsyncSession, venue_id: uuid.UUID, document_id: uuid.UUID
) -> SupplierBonusDocumentRevision | None:
    return (
        await db.execute(
            select(SupplierBonusDocumentRevision)
            .where(
                SupplierBonusDocumentRevision.venue_id == venue_id,
                SupplierBonusDocumentRevision.document_id == document_id,
            )
            .order_by(SupplierBonusDocumentRevision.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def document_allocated(db: AsyncSession, venue_id: uuid.UUID, document_id: uuid.UUID) -> int:
    allocated = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(SupplierBonusAllocation.amount_cents), 0)).where(
                    SupplierBonusAllocation.venue_id == venue_id,
                    SupplierBonusAllocation.document_id == document_id,
                )
            )
        ).scalar_one()
    )
    reversed_amount = int(
        (
            await db.execute(
                select(
                    func.coalesce(func.sum(SupplierBonusAllocationReversal.amount_cents), 0)
                ).where(
                    SupplierBonusAllocationReversal.venue_id == venue_id,
                    SupplierBonusAllocationReversal.document_id == document_id,
                )
            )
        ).scalar_one()
    )
    return allocated - reversed_amount


async def effective_document(db: AsyncSession, row: SupplierBonusDocument) -> BonusDocumentRead:
    revision = await latest_revision(db, row.venue_id, row.id)
    used = await document_allocated(db, row.venue_id, row.id)
    source = revision or row
    void = revision is not None and revision.kind == "void"
    return BonusDocumentRead(
        id=row.id,
        created_at=row.created_at,
        request_key=row.request_key,
        reason=row.reason,
        supplier_id=row.supplier_id,
        reference=row.reference,
        issued_on=source.issued_on,
        net_cents=source.net_cents,
        tax_cents=source.tax_cents,
        original_issued_on=row.issued_on,
        original_net_cents=row.net_cents,
        original_tax_cents=row.tax_cents,
        currency=row.currency,
        allocated_cents=used,
        remaining_cents=0 if void else source.net_cents - used,
        status="void" if void else "active",
        version=revision.version if revision else 1,
        effective_revision_id=revision.id if revision else None,
    )
