"""Supplier conditions and auditable bonus claims; no stock movement or payment side effects."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from app.gastro import purchasing
from app.gastro import service as svc
from app.gastro.inventory_models import StockOwner
from app.gastro.purchasing_bonus_models import (
    SupplierBonusAllocationReversal,
    SupplierBonusDocumentRevision,
)
from app.gastro.purchasing_bonus_schemas import (
    BonusAllocationReversalRead,
    BonusDocumentRevisionRead,
)
from app.gastro.purchasing_bonus_state import allocation_digest, effective_document
from app.gastro.purchasing_math import bonus_claim, earliest_delivery, priced_packs
from app.gastro.purchasing_models import (
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseOrder,
    PurchaseOrderLine,
)
from app.gastro.purchasing_terms_models import (
    SupplierBonusAgreement,
    SupplierBonusAllocation,
    SupplierBonusDocument,
    SupplierBonusStatement,
    SupplierOrderTerms,
)
from app.gastro.purchasing_terms_schemas import (
    BonusAgreementInput,
    BonusAgreementRead,
    BonusAllocationInput,
    BonusAllocationRead,
    BonusBalance,
    BonusDocumentInput,
    BonusDocumentRead,
    BonusPreview,
    BonusSnapshot,
    BonusSourceRead,
    BonusStatementInput,
    BonusStatementRead,
    ProductConditions,
    QuoteInput,
    QuoteLineRead,
    QuoteRead,
    SupplierRules,
    SupplierTermsInput,
    SupplierTermsRead,
)
from app.gastro.router import DB, Actor, private_response

router = APIRouter(dependencies=[Depends(private_response)])
bonus_router = APIRouter(dependencies=[Depends(private_response)])
PREFIX = "/venues/{venue_id}/purchasing"


async def agreement_for(
    db: DB, venue_id: uuid.UUID, agreement_id: uuid.UUID
) -> SupplierBonusAgreement:
    row = (
        await db.execute(
            select(SupplierBonusAgreement).where(
                SupplierBonusAgreement.venue_id == venue_id,
                SupplierBonusAgreement.id == agreement_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Bonusvereinbarung nicht gefunden.")
    return row


async def document_for(
    db: DB, venue_id: uuid.UUID, document_id: uuid.UUID
) -> SupplierBonusDocument:
    row = (
        await db.execute(
            select(SupplierBonusDocument).where(
                SupplierBonusDocument.venue_id == venue_id, SupplierBonusDocument.id == document_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Lieferantenbeleg nicht gefunden.")
    return row


async def claimed(db: DB, venue_id: uuid.UUID, agreement_id: uuid.UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.coalesce(func.sum(SupplierBonusStatement.delta_cents), 0)).where(
                    SupplierBonusStatement.venue_id == venue_id,
                    SupplierBonusStatement.agreement_id == agreement_id,
                )
            )
        ).scalar_one()
    )


async def allocated_to(db: DB, venue_id: uuid.UUID, agreement_id: uuid.UUID) -> int:
    allocated = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(SupplierBonusAllocation.amount_cents), 0)).where(
                    SupplierBonusAllocation.venue_id == venue_id,
                    SupplierBonusAllocation.agreement_id == agreement_id,
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
                    SupplierBonusAllocationReversal.agreement_id == agreement_id,
                )
            )
        ).scalar_one()
    )
    return allocated - reversed_amount


async def document_read(db: DB, row: SupplierBonusDocument) -> BonusDocumentRead:
    return await effective_document(db, row)


@router.post(
    PREFIX + "/supplier-terms",
    response_model=SupplierTermsRead,
    status_code=201,
    summary="Lieferfrist, Lieferkalender und Mindestbestellwert versionieren",
)
async def add_terms(
    venue_id: uuid.UUID, data: SupplierTermsInput, user: Actor, db: DB
) -> SupplierOrderTerms:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    previous = (
        await db.execute(
            select(SupplierOrderTerms).where(
                SupplierOrderTerms.venue_id == venue_id,
                SupplierOrderTerms.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if previous:
        if previous.request_hash != svc.digest(data):
            raise HTTPException(409, "Vorgangs-ID gehört zu anderen Lieferbedingungen.")
        return previous
    await purchasing.supplier_for(db, venue_id, data.supplier_id)
    latest = (
        await db.execute(
            select(SupplierOrderTerms)
            .where(
                SupplierOrderTerms.venue_id == venue_id,
                SupplierOrderTerms.supplier_id == data.supplier_id,
            )
            .order_by(SupplierOrderTerms.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    svc.check_version(latest.version if latest else 0, data.expected_version)
    if latest and data.effective_on < latest.effective_on:
        raise HTTPException(422, "Neue Lieferbedingungen dürfen ältere Gültigkeit nicht überholen.")
    row = SupplierOrderTerms(
        venue_id=venue_id,
        supplier_id=data.supplier_id,
        version=(latest.version if latest else 0) + 1,
        effective_on=data.effective_on,
        rules=data.rules.model_dump(mode="json", exclude_defaults=True),
        request_key=data.request_key,
        request_hash=svc.digest(data),
        reason=data.reason,
        actor_id=user.id,
    )
    db.add(row)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "purchasing.supplier_terms_added",
        row.id,
        {"supplier_id": str(data.supplier_id), "version": row.version},
        user.id,
    )
    return row


@router.post(
    PREFIX + "/quotes",
    response_model=QuoteRead,
    status_code=200,
    summary="Gebinde, Gratisware, Liefertermin und Mindestbestellwert prüfen",
)
async def quote_purchase(venue_id: uuid.UUID, data: QuoteInput, user: Actor, db: DB) -> QuoteRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    await purchasing.supplier_for(db, venue_id, data.supplier_id)
    now = datetime.now(UTC)
    today = now.astimezone(ZoneInfo(venue.timezone)).date()
    terms = await purchasing.terms_for(db, venue_id, data.supplier_id, today)
    rules = SupplierRules.model_validate(terms.rules if terms else {})
    lines: list[QuoteLineRead] = []
    for entry in data.lines:
        product = await purchasing.product_for(db, venue_id, entry.product_id)
        if product.supplier_id != data.supplier_id:
            raise HTTPException(422, "Lieferartikel gehört zu einem anderen Lieferanten.")
        price = await purchasing.price_for(db, venue_id, product.id, today)
        if price is None or price.id != entry.price_id:
            raise HTTPException(409, "Preis ist nicht mehr aktuell. Bitte neu laden.")
        conditions = ProductConditions.model_validate(price.conditions)
        applied, bonus_packs = priced_packs(entry.packs, price.pack_price_cents, conditions)
        total_quantity = product.pack_quantity * (entry.packs + bonus_packs)
        if total_quantity > 999999999:
            raise HTTPException(422, "Bestellmenge ist zu groß.")
        lines.append(
            QuoteLineRead(
                product_id=product.id,
                price_id=price.id,
                packs=entry.packs,
                bonus_packs=bonus_packs,
                paid_quantity=product.pack_quantity * entry.packs,
                ordered_bonus_quantity=product.pack_quantity * bonus_packs,
                ordered_quantity=total_quantity,
                pack_price_cents=applied,
                net_cents=applied * entry.packs,
                conditions=conditions,
            )
        )
    amount = sum(line.net_cents for line in lines)
    if amount > 1000000000:
        raise HTTPException(422, "Bestellwert ist zu groß.")
    arrival = earliest_delivery(now, rules, venue.timezone) if terms else None
    result = QuoteRead(
        supplier_id=data.supplier_id,
        supplier_terms_id=terms.id if terms else None,
        lines=lines,
        earliest_delivery_on=arrival,
        shortfall_to_minimum_net_cents=max(0, rules.minimum_order_net_cents - amount),
        net_cents=amount,
        expected_delivery_feasible=(
            (not data.expected_on or data.expected_on >= arrival) if arrival else None
        ),
        fingerprint="",
    )
    result.fingerprint = svc.digest(result)
    return result


@bonus_router.post(
    PREFIX + "/bonus-agreements",
    response_model=BonusAgreementRead,
    status_code=201,
    summary="Lieferantenbonus mit expliziter Rechnungsbasis festhalten",
)
async def create_agreement(
    venue_id: uuid.UUID, data: BonusAgreementInput, user: Actor, db: DB
) -> SupplierBonusAgreement:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    previous = (
        await db.execute(
            select(SupplierBonusAgreement).where(
                SupplierBonusAgreement.venue_id == venue_id,
                SupplierBonusAgreement.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if previous:
        if previous.request_hash != svc.digest(data):
            raise HTTPException(409, "Vorgangs-ID gehört zu einer anderen Bonusvereinbarung.")
        return previous
    await purchasing.supplier_for(db, venue_id, data.supplier_id)
    existing = (
        await db.execute(
            select(SupplierBonusAgreement.id).where(
                SupplierBonusAgreement.venue_id == venue_id,
                SupplierBonusAgreement.supplier_id == data.supplier_id,
                (
                    (SupplierBonusAgreement.period_start <= data.period_end)
                    & (SupplierBonusAgreement.period_end >= data.period_start)
                )
                | (SupplierBonusAgreement.reference == data.reference),
            )
        )
    ).first()
    if existing:
        raise HTTPException(
            409, "Referenz oder Bonusperiode überschneidet sich mit einer bestehenden Vereinbarung."
        )
    row = SupplierBonusAgreement(
        venue_id=venue_id,
        currency=venue.currency,
        actor_id=user.id,
        request_hash=svc.digest(data),
        **data.model_dump(),
    )
    db.add(row)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "purchasing.bonus_agreement_created",
        row.id,
        {"supplier_id": str(row.supplier_id)},
        user.id,
    )
    return row


async def preview_bonus(db: DB, agreement: SupplierBonusAgreement, timezone: str) -> BonusPreview:
    rows = (
        await db.execute(
            select(PurchaseInvoice, PurchaseInvoiceLine)
            .join(PurchaseInvoiceLine, PurchaseInvoiceLine.invoice_id == PurchaseInvoice.id)
            .join(PurchaseOrderLine, PurchaseOrderLine.id == PurchaseInvoiceLine.purchase_line_id)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.order_id)
            .join(StockOwner, StockOwner.id == PurchaseOrder.owner_id)
            .where(
                PurchaseInvoice.venue_id == agreement.venue_id,
                PurchaseInvoiceLine.venue_id == agreement.venue_id,
                PurchaseOrderLine.venue_id == agreement.venue_id,
                PurchaseOrder.venue_id == agreement.venue_id,
                StockOwner.venue_id == agreement.venue_id,
                StockOwner.kind == "own",
                PurchaseInvoice.supplier_id == agreement.supplier_id,
                PurchaseInvoice.currency == agreement.currency,
                PurchaseInvoice.status == "approved",
                PurchaseInvoice.issued_on >= agreement.period_start,
                PurchaseInvoice.issued_on <= agreement.period_end,
            )
            .order_by(PurchaseInvoice.id, PurchaseInvoiceLine.id)
        )
    ).all()
    sources: list[BonusSourceRead] = []
    blockers: list[str] = []
    for invoice, line in rows:
        if invoice.decided_at is None:
            blockers.append(f"Rechnung {invoice.number}: historischer Freigabezeitpunkt fehlt.")
            continue
        sources.append(
            BonusSourceRead(
                invoice_id=invoice.id,
                purchase_line_id=line.purchase_line_id,
                issued_on=invoice.issued_on,
                decided_at=invoice.decided_at,
                quantity=line.quantity,
                net_cents=line.net_cents,
            )
        )
    if agreement.period_end >= datetime.now(ZoneInfo(timezone)).date():
        blockers.append("Die Bonusperiode ist noch nicht abgeschlossen.")
    total = sum(source.net_cents for source in sources)
    already = await claimed(db, agreement.venue_id, agreement.id)
    amount = bonus_claim(total, agreement.rate_bps, agreement.threshold_cents, agreement.mode)
    if amount < already:
        blockers.append(
            "Die Quellenbasis unterschreitet den festgeschriebenen Anspruch; eine Korrektur ist erforderlich."
        )
    result = BonusPreview(
        agreement_id=agreement.id,
        currency=agreement.currency,
        period_start=agreement.period_start,
        period_end=agreement.period_end,
        sources=sources,
        source_net_cents=total,
        claim_cents=amount,
        already_stated_cents=already,
        delta_cents=amount - already,
        fingerprint="",
        blocking_reasons=blockers,
    )
    result.fingerprint = svc.digest(result)
    return result


@bonus_router.get(
    PREFIX + "/bonus-agreements/{agreement_id}/preview",
    response_model=BonusPreview,
    status_code=200,
    summary="Bonusanspruch mit konkreten Rechnungsquellen prüfen",
)
async def bonus_preview(
    venue_id: uuid.UUID, agreement_id: uuid.UUID, user: Actor, db: DB
) -> BonusPreview:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    return await preview_bonus(db, await agreement_for(db, venue_id, agreement_id), venue.timezone)


@bonus_router.post(
    PREFIX + "/bonus-statements",
    response_model=BonusStatementRead,
    status_code=201,
    summary="Bonusanspruch oder spätere Anspruchsdifferenz unveränderlich festschreiben",
)
async def state_bonus(
    venue_id: uuid.UUID, data: BonusStatementInput, user: Actor, db: DB
) -> SupplierBonusStatement:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    previous = (
        await db.execute(
            select(SupplierBonusStatement).where(
                SupplierBonusStatement.venue_id == venue_id,
                SupplierBonusStatement.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if previous:
        if previous.request_hash != svc.digest(data):
            raise HTTPException(409, "Vorgangs-ID gehört zu einer anderen Bonusabrechnung.")
        return previous
    agreement = await agreement_for(db, venue_id, data.agreement_id)
    preview = await preview_bonus(db, agreement, venue.timezone)
    if preview.blocking_reasons:
        raise HTTPException(409, " ".join(preview.blocking_reasons))
    if preview.fingerprint != data.fingerprint:
        raise HTTPException(409, "Bonusquellen haben sich geändert. Vorschau erneut prüfen.")
    count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(SupplierBonusStatement)
                .where(
                    SupplierBonusStatement.venue_id == venue_id,
                    SupplierBonusStatement.agreement_id == agreement.id,
                )
            )
        ).scalar_one()
    )
    if count and preview.delta_cents == 0:
        raise HTTPException(409, "Es gibt keinen zusätzlichen Bonusanspruch.")
    row = SupplierBonusStatement(
        venue_id=venue_id,
        agreement_id=agreement.id,
        sequence=count + 1,
        delta_cents=preview.delta_cents,
        snapshot=preview.model_dump(mode="json"),
        request_key=data.request_key,
        request_hash=svc.digest(data),
        reason=data.reason,
        actor_id=user.id,
    )
    db.add(row)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "purchasing.bonus_stated",
        row.id,
        {"agreement_id": str(agreement.id), "delta_cents": row.delta_cents},
        user.id,
    )
    return row


@bonus_router.post(
    PREFIX + "/bonus-documents",
    response_model=BonusDocumentRead,
    status_code=201,
    summary="Tatsächlich erhaltenen Lieferantenbonusbeleg erfassen",
)
async def create_document(
    venue_id: uuid.UUID, data: BonusDocumentInput, user: Actor, db: DB
) -> BonusDocumentRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    previous = (
        await db.execute(
            select(SupplierBonusDocument).where(
                SupplierBonusDocument.venue_id == venue_id,
                SupplierBonusDocument.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if previous:
        if previous.request_hash != svc.digest(data):
            raise HTTPException(409, "Vorgangs-ID gehört zu einem anderen Lieferantenbeleg.")
        return await document_read(db, previous)
    await purchasing.supplier_for(db, venue_id, data.supplier_id)
    if data.currency != venue.currency:
        raise HTTPException(422, "Belegwährung muss zur Betriebswährung passen.")
    if (
        await db.execute(
            select(SupplierBonusDocument.id).where(
                SupplierBonusDocument.venue_id == venue_id,
                SupplierBonusDocument.supplier_id == data.supplier_id,
                SupplierBonusDocument.reference == data.reference,
            )
        )
    ).first():
        raise HTTPException(409, "Dieser Lieferantenbeleg ist bereits erfasst.")
    row = SupplierBonusDocument(
        venue_id=venue_id, request_hash=svc.digest(data), actor_id=user.id, **data.model_dump()
    )
    db.add(row)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "purchasing.bonus_document_recorded",
        row.id,
        {"supplier_id": str(row.supplier_id), "net_cents": row.net_cents},
        user.id,
    )
    return await document_read(db, row)


@bonus_router.post(
    PREFIX + "/bonus-allocations",
    response_model=BonusAllocationRead,
    status_code=201,
    summary="Belegnetto einer offenen Bonusforderung zuordnen",
)
async def allocate_bonus(
    venue_id: uuid.UUID, data: BonusAllocationInput, user: Actor, db: DB
) -> SupplierBonusAllocation:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    previous = (
        await db.execute(
            select(SupplierBonusAllocation).where(
                SupplierBonusAllocation.venue_id == venue_id,
                SupplierBonusAllocation.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if previous:
        if previous.request_hash != allocation_digest(data):
            raise HTTPException(409, "Vorgangs-ID gehört zu einer anderen Bonuszuordnung.")
        return previous
    agreement = await agreement_for(db, venue_id, data.agreement_id)
    document = await document_for(db, venue_id, data.document_id)
    if agreement.supplier_id != document.supplier_id or agreement.currency != document.currency:
        raise HTTPException(
            422, "Lieferant oder Währung von Bonusanspruch und Beleg passen nicht zusammen."
        )
    current = await document_read(db, document)
    if current.status != "active":
        raise HTTPException(409, "Die Dokumenterfassung wurde verworfen.")
    if data.document_revision_id != current.effective_revision_id:
        raise HTTPException(409, "Die Dokumentfassung hat sich geändert. Bitte erneut prüfen.")
    available = current.remaining_cents
    remaining = await claimed(db, venue_id, agreement.id) - await allocated_to(
        db, venue_id, agreement.id
    )
    if data.amount_cents > min(available, remaining):
        raise HTTPException(
            409, "Zuordnung überschreitet offenen Bonusanspruch oder verfügbares Belegnetto."
        )
    row = SupplierBonusAllocation(
        venue_id=venue_id,
        request_hash=allocation_digest(data),
        actor_id=user.id,
        **data.model_dump(),
    )
    db.add(row)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "purchasing.bonus_allocated",
        row.id,
        {"agreement_id": str(agreement.id), "amount_cents": row.amount_cents},
        user.id,
    )
    return row


@bonus_router.get(
    PREFIX + "/bonuses",
    response_model=BonusSnapshot,
    status_code=200,
    summary="Bonusvereinbarungen, Ansprüche, erhaltene Belege und Restforderungen anzeigen",
)
async def bonus_snapshot(venue_id: uuid.UUID, user: Actor, db: DB) -> BonusSnapshot:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    agreements = list(
        (
            await db.execute(
                select(SupplierBonusAgreement)
                .where(SupplierBonusAgreement.venue_id == venue_id)
                .order_by(SupplierBonusAgreement.period_start, SupplierBonusAgreement.id)
            )
        ).scalars()
    )
    statements = list(
        (
            await db.execute(
                select(SupplierBonusStatement)
                .where(SupplierBonusStatement.venue_id == venue_id)
                .order_by(SupplierBonusStatement.agreement_id, SupplierBonusStatement.sequence)
            )
        ).scalars()
    )
    documents = list(
        (
            await db.execute(
                select(SupplierBonusDocument)
                .where(SupplierBonusDocument.venue_id == venue_id)
                .order_by(SupplierBonusDocument.created_at, SupplierBonusDocument.id)
            )
        ).scalars()
    )
    allocations = list(
        (
            await db.execute(
                select(SupplierBonusAllocation)
                .where(SupplierBonusAllocation.venue_id == venue_id)
                .order_by(SupplierBonusAllocation.created_at, SupplierBonusAllocation.id)
            )
        ).scalars()
    )
    revisions = list(
        (
            await db.execute(
                select(SupplierBonusDocumentRevision)
                .where(SupplierBonusDocumentRevision.venue_id == venue_id)
                .order_by(
                    SupplierBonusDocumentRevision.document_id, SupplierBonusDocumentRevision.version
                )
            )
        ).scalars()
    )
    reversals = list(
        (
            await db.execute(
                select(SupplierBonusAllocationReversal)
                .where(SupplierBonusAllocationReversal.venue_id == venue_id)
                .order_by(
                    SupplierBonusAllocationReversal.created_at, SupplierBonusAllocationReversal.id
                )
            )
        ).scalars()
    )
    balances: list[BonusBalance] = []
    for agreement in agreements:
        stated = sum(row.delta_cents for row in statements if row.agreement_id == agreement.id)
        used = sum(row.amount_cents for row in allocations if row.agreement_id == agreement.id)
        used -= sum(row.amount_cents for row in reversals if row.agreement_id == agreement.id)
        balances.append(
            BonusBalance(
                agreement_id=agreement.id,
                claimed_cents=stated,
                allocated_cents=used,
                remaining_cents=stated - used,
            )
        )
    return BonusSnapshot(
        document_revisions=[BonusDocumentRevisionRead.model_validate(row) for row in revisions],
        reversals=[BonusAllocationReversalRead.model_validate(row) for row in reversals],
        agreements=[BonusAgreementRead.model_validate(row) for row in agreements],
        statements=[BonusStatementRead.model_validate(row) for row in statements],
        documents=[await document_read(db, row) for row in documents],
        allocations=[BonusAllocationRead.model_validate(row) for row in allocations],
        balances=balances,
    )
