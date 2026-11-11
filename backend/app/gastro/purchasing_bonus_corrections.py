"""Manager-authorized counter-documents, never edits to original bonus evidence."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.gastro import service as svc
from app.gastro.inventory_schemas import BookingInput
from app.gastro.purchasing_bonus_models import (
    SupplierBonusAllocationReversal,
    SupplierBonusDocumentRevision,
)
from app.gastro.purchasing_bonus_schemas import (
    BonusAllocationReversalRead,
    BonusDocumentRevisionInput,
    BonusDocumentRevisionRead,
    ScopedBonusDocumentRevisionInput,
    ScopedBonusReversalInput,
)
from app.gastro.purchasing_bonus_state import effective_document, latest_revision
from app.gastro.purchasing_terms import document_for
from app.gastro.purchasing_terms_models import SupplierBonusAllocation
from app.gastro.router import DB, Actor, private_response

router = APIRouter(dependencies=[Depends(private_response)])
PREFIX = "/venues/{venue_id}/purchasing"


@router.post(
    PREFIX + "/bonus-allocations/{allocation_id}/reverse",
    response_model=BonusAllocationReversalRead,
    status_code=201,
    summary="Eine Bonuszuordnung mit unveränderlichem Gegenbeleg vollständig zurücknehmen",
)
async def reverse_allocation(
    venue_id: uuid.UUID, allocation_id: uuid.UUID, data: BookingInput, user: Actor, db: DB
) -> SupplierBonusAllocationReversal:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    scoped = ScopedBonusReversalInput(allocation_id=allocation_id, **data.model_dump())
    previous = (
        await db.execute(
            select(SupplierBonusAllocationReversal).where(
                SupplierBonusAllocationReversal.venue_id == venue_id,
                SupplierBonusAllocationReversal.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if previous:
        if previous.request_hash != svc.digest(scoped):
            raise HTTPException(409, "Vorgangs-ID gehört zu einer anderen Zuordnungsrücknahme.")
        return previous
    original = (
        await db.execute(
            select(SupplierBonusAllocation).where(
                SupplierBonusAllocation.venue_id == venue_id,
                SupplierBonusAllocation.id == allocation_id,
            )
        )
    ).scalar_one_or_none()
    if original is None:
        raise HTTPException(404, "Bonuszuordnung nicht gefunden.")
    if (
        await db.execute(
            select(SupplierBonusAllocationReversal.id).where(
                SupplierBonusAllocationReversal.venue_id == venue_id,
                SupplierBonusAllocationReversal.allocation_id == allocation_id,
            )
        )
    ).first():
        raise HTTPException(409, "Diese Bonuszuordnung wurde bereits zurückgenommen.")
    row = SupplierBonusAllocationReversal(
        venue_id=venue_id,
        allocation_id=original.id,
        document_id=original.document_id,
        document_revision_id=original.document_revision_id,
        agreement_id=original.agreement_id,
        amount_cents=original.amount_cents,
        request_key=data.request_key,
        request_hash=svc.digest(scoped),
        reason=data.reason,
        actor_id=user.id,
    )
    db.add(row)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "purchasing.bonus_allocation_reversed",
        row.id,
        {"allocation_id": str(original.id), "amount_cents": row.amount_cents},
        user.id,
    )
    return row


@router.post(
    PREFIX + "/bonus-documents/{document_id}/revisions",
    response_model=BonusDocumentRevisionRead,
    status_code=201,
    summary="Fehlerhafte Bonusdokumenterfassung durch eine neue unveränderliche Version berichtigen",
)
async def revise_document(
    venue_id: uuid.UUID,
    document_id: uuid.UUID,
    data: BonusDocumentRevisionInput,
    user: Actor,
    db: DB,
) -> SupplierBonusDocumentRevision:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    scoped = ScopedBonusDocumentRevisionInput(document_id=document_id, **data.model_dump())
    previous = (
        await db.execute(
            select(SupplierBonusDocumentRevision).where(
                SupplierBonusDocumentRevision.venue_id == venue_id,
                SupplierBonusDocumentRevision.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if previous:
        if previous.request_hash != svc.digest(scoped):
            raise HTTPException(409, "Vorgangs-ID gehört zu einer anderen Dokumentkorrektur.")
        return previous
    document = await document_for(db, venue_id, document_id)
    current = await effective_document(db, document)
    svc.check_version(current.version, data.expected_version)
    if current.allocated_cents:
        raise HTTPException(409, "Zuerst alle aktiven Zuordnungen dieses Belegs zurücknehmen.")
    if data.kind == "void" and current.status == "void":
        raise HTTPException(409, "Die Dokumenterfassung ist bereits verworfen.")
    latest = await latest_revision(db, venue_id, document_id)
    if data.kind == "corrected":
        # Schema validation requires all three fields. This branch also narrows their types.
        if data.issued_on is None or data.net_cents is None or data.tax_cents is None:
            raise HTTPException(422, "Korrektur benötigt vollständige Belegwerte.")
        issued_on, net_cents, tax_cents = data.issued_on, data.net_cents, data.tax_cents
        if current.status == "active" and (issued_on, net_cents, tax_cents) == (
            current.issued_on,
            current.net_cents,
            current.tax_cents,
        ):
            raise HTTPException(409, "Die Korrektur enthält keine geänderten Belegwerte.")
    else:
        issued_on, net_cents, tax_cents = current.issued_on, current.net_cents, current.tax_cents
    row = SupplierBonusDocumentRevision(
        venue_id=venue_id,
        document_id=document.id,
        previous_revision_id=latest.id if latest else None,
        version=current.version + 1,
        kind=data.kind,
        issued_on=issued_on,
        net_cents=net_cents,
        tax_cents=tax_cents,
        request_key=data.request_key,
        request_hash=svc.digest(scoped),
        reason=data.reason,
        actor_id=user.id,
    )
    db.add(row)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "purchasing.bonus_document_revised",
        row.id,
        {"document_id": str(document.id), "version": row.version, "kind": row.kind},
        user.id,
    )
    return row
