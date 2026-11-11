"""Consignment recognition is separate from custody, cash collection and tax invoicing."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import JsonValue
from sqlalchemy import func, select

from app.gastro import inventory
from app.gastro import service as svc
from app.gastro.cash import command_hash, units_for
from app.gastro.cash_models import CashEntry
from app.gastro.inventory_models import StockLot, StockMovement, StockOperation, StockOwner
from app.gastro.inventory_schemas import BookingInput, OperationKind
from app.gastro.models import Order, Venue
from app.gastro.partners_models import (
    LoanAccount,
    LoanEntry,
    PartnerContract,
    PartnerEvent,
    PartnerPosting,
    PartnerSettlement,
    PartnerTerms,
)
from app.gastro.partners_schemas import (
    CandidateRead,
    ContractInput,
    ContractRead,
    EventRead,
    LoanAccountInput,
    LoanAccountRead,
    LoanEntryInput,
    LoanEntryRead,
    LossCandidate,
    LossInput,
    PartnerRules,
    PartnerSnapshot,
    PartnerStockInput,
    PostingRead,
    RefundCandidate,
    RefundInput,
    SaleCandidate,
    SaleInput,
    SettlementComponent,
    SettlementInput,
    SettlementPreview,
    SettlementRead,
    TermsRead,
    VersionInput,
)
from app.gastro.purchasing import cents
from app.gastro.recipes import RecipeVersion
from app.gastro.router import DB, Actor, private_response
from app.gastro.stock_availability import reserved_at

router = APIRouter(dependencies=[Depends(private_response)])
PREFIX = "/venues/{venue_id}/partners"


def today(venue: Venue) -> date:
    return datetime.now(ZoneInfo(venue.timezone)).date()


def month_of(value: date) -> date:
    return value.replace(day=1)


def next_month(value: date) -> date:
    return date(value.year + (value.month == 12), value.month % 12 + 1, 1)


async def contract_for(db: DB, venue_id: uuid.UUID, contract_id: uuid.UUID) -> PartnerContract:
    row = (
        await db.execute(
            select(PartnerContract).where(
                PartnerContract.venue_id == venue_id, PartnerContract.id == contract_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Partnervertrag nicht gefunden.")
    return row


async def terms_for(
    db: DB, contract: PartnerContract, on: date, *, require_active: bool = True
) -> PartnerTerms:
    row = (
        await db.execute(
            select(PartnerTerms)
            .where(
                PartnerTerms.venue_id == contract.venue_id,
                PartnerTerms.contract_id == contract.id,
                PartnerTerms.effective_on <= on,
            )
            .order_by(PartnerTerms.effective_on.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None or (require_active and not row.active):
        raise HTTPException(409, "Für dieses Datum besteht kein aktiver Partnervertrag.")
    return row


async def contract_read(db: DB, contract: PartnerContract) -> ContractRead:
    versions = (
        (
            await db.execute(
                select(PartnerTerms)
                .where(
                    PartnerTerms.venue_id == contract.venue_id,
                    PartnerTerms.contract_id == contract.id,
                )
                .order_by(PartnerTerms.version)
            )
        )
        .scalars()
        .all()
    )
    return ContractRead(
        id=contract.id,
        created_at=contract.created_at,
        name=contract.name,
        owner_id=contract.owner_id,
        item_id=contract.item_id,
        menu_item_id=contract.menu_item_id,
        currency=contract.currency,
        terms=[TermsRead.model_validate(row) for row in versions],
    )


async def owner_for(db: DB, venue_id: uuid.UUID, owner_id: uuid.UUID) -> StockOwner:
    row = (
        await db.execute(
            select(StockOwner).where(StockOwner.venue_id == venue_id, StockOwner.id == owner_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Eigentümer nicht gefunden.")
    if row.kind != "partner":
        raise HTTPException(422, "Ein Partner-Eigentümer ist erforderlich.")
    return row


@router.post(
    PREFIX + "/contracts",
    response_model=ContractRead,
    status_code=201,
    summary="Partnervertrag mit eingefrorenen Anfangsbedingungen anlegen",
)
async def create_contract(
    venue_id: uuid.UUID, data: ContractInput, user: Actor, db: DB
) -> ContractRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    previous = (
        await db.execute(
            select(PartnerContract).where(
                PartnerContract.venue_id == venue_id,
                PartnerContract.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if previous:
        if previous.request_hash != svc.digest(data):
            raise HTTPException(409, "Vorgangs-ID wurde mit anderen Vertragsbedingungen verwendet.")
        return await contract_read(db, previous)
    await owner_for(db, venue_id, data.owner_id)
    item = await inventory.item_for(db, venue_id, data.item_id)
    await svc.menu_for_venue(db, venue_id, data.menu_item_id)
    inventory.validate_quantity(item, data.stock_per_sale)
    if (
        await db.execute(
            select(RecipeVersion.id).where(
                RecipeVersion.venue_id == venue_id,
                RecipeVersion.menu_item_id == data.menu_item_id,
            )
        )
    ).first():
        raise HTTPException(
            409,
            "Dieser Menüartikel besitzt eine Eigenwaren-Rezeptur. Für Partner-Wiederverkauf einen eigenen Menüartikel ohne Rezeptur verwenden.",
        )
    if (
        await db.execute(
            select(PartnerContract.id).where(
                PartnerContract.venue_id == venue_id,
                PartnerContract.menu_item_id == data.menu_item_id,
            )
        )
    ).first():
        raise HTTPException(409, "Dieser Menüartikel besitzt bereits einen Partnervertrag.")
    contract = PartnerContract(
        venue_id=venue_id,
        owner_id=data.owner_id,
        item_id=data.item_id,
        menu_item_id=data.menu_item_id,
        name=data.name,
        currency=venue.currency,
        request_key=data.request_key,
        request_hash=svc.digest(data),
        actor_id=user.id,
    )
    db.add(contract)
    await db.flush()
    db.add(
        PartnerTerms(
            venue_id=venue_id,
            contract_id=contract.id,
            version=1,
            effective_on=data.effective_on,
            active=data.active,
            stock_per_sale=data.stock_per_sale,
            rules=data.rules.model_dump(mode="json"),
            request_key=uuid.uuid5(data.request_key, "initial-terms"),
            request_hash=svc.digest(data),
            actor_id=user.id,
        )
    )
    await db.flush()
    return await contract_read(db, contract)


@router.post(
    PREFIX + "/contracts/{contract_id}/terms",
    response_model=ContractRead,
    status_code=201,
    summary="Neue Vertragsbedingungen ab einem künftigen Monat versionieren",
)
async def create_terms(
    venue_id: uuid.UUID, contract_id: uuid.UUID, data: VersionInput, user: Actor, db: DB
) -> ContractRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    contract = await contract_for(db, venue_id, contract_id)
    fingerprint = command_hash("partner-terms", contract_id, data)
    previous = (
        await db.execute(
            select(PartnerTerms).where(
                PartnerTerms.venue_id == venue_id, PartnerTerms.request_key == data.request_key
            )
        )
    ).scalar_one_or_none()
    if previous:
        if previous.request_hash != fingerprint:
            raise HTTPException(409, "Vorgangs-ID wurde für andere Vertragsbedingungen verwendet.")
        return await contract_read(db, contract)
    latest = (
        await db.execute(
            select(PartnerTerms)
            .where(PartnerTerms.contract_id == contract.id)
            .order_by(PartnerTerms.version.desc())
            .limit(1)
        )
    ).scalar_one()
    if latest.version != data.expected_version:
        raise HTTPException(409, "Vertragsstand hat sich geändert. Bitte neu laden.")
    if data.effective_on <= max(latest.effective_on, month_of(today(venue))):
        raise HTTPException(
            422,
            "Neue Bedingungen müssen nach dem aktuellen und zuletzt geplanten Vertragsmonat beginnen.",
        )
    inventory.validate_quantity(
        await inventory.item_for(db, venue_id, contract.item_id), data.stock_per_sale
    )
    db.add(
        PartnerTerms(
            venue_id=venue_id,
            contract_id=contract.id,
            version=latest.version + 1,
            effective_on=data.effective_on,
            active=data.active,
            stock_per_sale=data.stock_per_sale,
            rules=data.rules.model_dump(mode="json"),
            request_key=data.request_key,
            request_hash=fingerprint,
            actor_id=user.id,
        )
    )
    await db.flush()
    return await contract_read(db, contract)


async def posting_read(db: DB, posting: PartnerPosting) -> PostingRead:
    events = (
        (
            await db.execute(
                select(PartnerEvent)
                .where(
                    PartnerEvent.venue_id == posting.venue_id, PartnerEvent.posting_id == posting.id
                )
                .order_by(PartnerEvent.unit, PartnerEvent.id)
            )
        )
        .scalars()
        .all()
    )
    return PostingRead(
        id=posting.id,
        created_at=posting.created_at,
        contract_id=posting.contract_id,
        request_key=posting.request_key,
        kind=posting.kind,
        events=[EventRead.model_validate(row) for row in events],
    )


async def posting_replay(
    db: DB, venue_id: uuid.UUID, kind: str, data: BookingInput
) -> PostingRead | None:
    row = (
        await db.execute(
            select(PartnerPosting).where(
                PartnerPosting.venue_id == venue_id, PartnerPosting.request_key == data.request_key
            )
        )
    ).scalar_one_or_none()
    if row:
        if row.kind != kind or row.request_hash != svc.digest(data):
            raise HTTPException(409, "Vorgangs-ID wurde für eine andere Partnerbuchung verwendet.")
        return await posting_read(db, row)
    return None


async def new_posting(
    db: DB, contract: PartnerContract, actor_id: uuid.UUID, kind: str, data: BookingInput
) -> PartnerPosting:
    row = PartnerPosting(
        venue_id=contract.venue_id,
        contract_id=contract.id,
        kind=kind,
        request_key=data.request_key,
        request_hash=svc.digest(data),
        reason=data.reason,
        actor_id=actor_id,
    )
    db.add(row)
    await db.flush()
    return row


async def posting_month(db: DB, venue: Venue, contract: PartnerContract, source: date) -> date:
    original = month_of(source)
    closed = (
        await db.execute(
            select(PartnerSettlement.id).where(
                PartnerSettlement.contract_id == contract.id, PartnerSettlement.month == original
            )
        )
    ).first()
    return max(original, month_of(today(venue))) if closed else original


async def draw_stock(
    db: DB,
    venue: Venue,
    contract: PartnerContract,
    actor_id: uuid.UUID,
    data: BookingInput,
    amount: Decimal,
    order_id: uuid.UUID,
    line_id: uuid.UUID,
) -> uuid.UUID:
    lots = (
        (
            await db.execute(
                select(StockLot)
                .where(
                    StockLot.venue_id == venue.id,
                    StockLot.owner_id == contract.owner_id,
                    StockLot.item_id == contract.item_id,
                    StockLot.blocked.is_(False),
                    (StockLot.expires_on.is_(None) | (StockLot.expires_on >= today(venue))),
                )
                .order_by(StockLot.expires_on.asc().nullslast(), StockLot.created_at, StockLot.id)
            )
        )
        .scalars()
        .all()
    )
    remaining = amount
    moves: list[tuple[StockLot, uuid.UUID, Decimal]] = []
    for lot in lots:
        balances = (
            await db.execute(
                select(StockMovement.location_id, func.sum(StockMovement.quantity))
                .where(StockMovement.venue_id == venue.id, StockMovement.lot_id == lot.id)
                .group_by(StockMovement.location_id)
                .order_by(StockMovement.location_id)
            )
        ).all()
        for location_id, raw in balances:
            held = await reserved_at(db, venue.id, lot.id, location_id)
            taken = min(remaining, max(Decimal(0), Decimal(str(raw)) - held))
            if taken:
                moves.append((lot, location_id, -taken))
                remaining -= taken
            if not remaining:
                break
        if not remaining:
            break
    if remaining:
        raise HTTPException(
            409, "Nicht genügend freigegebene, haltbare Ware dieses Partners verfügbar."
        )
    if await inventory.replay(db, venue.id, "consume", data):
        raise HTTPException(409, "Lagerbeleg existiert ohne passende Partnerbuchung.")
    operation = await inventory.post_movements(
        db,
        venue.id,
        actor_id,
        "consume",
        data,
        moves,
        {
            "partner_contract_id": str(contract.id),
            "order_id": str(order_id),
            "line_id": str(line_id),
        },
    )
    return operation.id


@router.post(
    PREFIX + "/sales",
    response_model=PostingRead,
    status_code=201,
    summary="Bezahlte Verkaufseinheiten mit Partnerbestand und Kassenbelegen verknüpfen",
)
async def recognize_sales(venue_id: uuid.UUID, data: SaleInput, user: Actor, db: DB) -> PostingRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    replay = await posting_replay(db, venue_id, "sale", data)
    if replay:
        return replay
    contract = await contract_for(db, venue_id, data.contract_id)
    order = await svc.order_for_venue(db, venue_id, data.order_id)
    line = next(
        (line for line in order.lines if str(line.get("line_id")) == str(data.line_id)), None
    )
    if (
        line is None
        or str(line.get("item_id")) != str(contract.menu_item_id)
        or line.get("kind", "product") != "product"
    ):
        raise HTTPException(422, "Die Bestellposition gehört nicht zu diesem Partnerartikel.")
    if line.get("recipe_id"):
        raise HTTPException(
            409,
            "Diese Position wird bereits über eine Rezeptur verbraucht. Partner-Wiederverkauf benötigt einen eigenen Artikel ohne Rezeptur.",
        )
    if order.fulfillment_status != "served" or order.currency != contract.currency:
        raise HTTPException(
            409, "Partnerverkäufe benötigen einen servierten Bon in Vertragswährung."
        )
    terms = await terms_for(
        db, contract, order.created_at.astimezone(ZoneInfo(venue.timezone)).date()
    )
    rules = PartnerRules.model_validate(terms.rules)
    entries = list(
        (
            await db.execute(
                select(CashEntry)
                .where(CashEntry.venue_id == venue_id, CashEntry.order_id == order.id)
                .order_by(CashEntry.created_at, CashEntry.id)
            )
        )
        .scalars()
        .all()
    )
    units = {
        unit.unit: unit
        for unit in units_for(order, entries, virtual_voucher=False)
        if unit.line_id == str(data.line_id)
    }
    recognized: list[tuple[int, int, int, date, list[dict[str, JsonValue]]]] = []
    for index in data.units:
        unit = units.get(index)
        if unit is None or unit.cancelled or unit.remaining or unit.gross <= 0:
            raise HTTPException(
                409,
                "Jede übernommene Verkaufseinheit benötigt vollständige positive Zahlungsbelege.",
            )
        if (
            await db.execute(
                select(PartnerEvent.id).where(
                    PartnerEvent.venue_id == venue_id,
                    PartnerEvent.order_id == order.id,
                    PartnerEvent.line_id == data.line_id,
                    PartnerEvent.unit == index,
                    PartnerEvent.kind == "sale",
                )
            )
        ).first():
            raise HTTPException(
                409, "Diese Verkaufseinheit wurde bereits für einen Partner übernommen."
            )
        proofs: list[dict[str, JsonValue]] = []
        paid_on = terms.effective_on
        for entry in entries:
            if entry.kind != "sale":
                continue
            for allocation in entry.allocations:
                if (
                    str(allocation["line_id"]) == str(data.line_id)
                    and int(str(allocation["unit"])) == index
                ):
                    proofs.append({"cash_entry_id": str(entry.id), **allocation})
                    paid_on = max(
                        paid_on, entry.created_at.astimezone(ZoneInfo(venue.timezone)).date()
                    )
        if not proofs or sum(int(str(row["amount_cents"])) for row in proofs) != unit.gross:
            raise HTTPException(409, "Kassenbelege passen nicht zum eingefrorenen Positionspreis.")
        recognized.append((index, unit.gross, unit.tax, paid_on, proofs))
    # Economic terms are frozen at order time, even when payment arrives in a later month.
    source = month_of(order.created_at.astimezone(ZoneInfo(venue.timezone)).date())
    operation_id = await draw_stock(
        db,
        venue,
        contract,
        user.id,
        BookingInput(request_key=uuid.uuid5(data.request_key, "sale-stock"), reason=data.reason),
        terms.stock_per_sale * len(recognized),
        order.id,
        data.line_id,
    )
    posting = await new_posting(db, contract, user.id, "sale", data)
    posting_period = await posting_month(db, venue, contract, source)
    for index, gross, tax, paid_on, proofs in recognized:
        db.add(
            PartnerEvent(
                venue_id=venue_id,
                contract_id=contract.id,
                terms_id=terms.id,
                posting_id=posting.id,
                kind="sale",
                order_id=order.id,
                line_id=data.line_id,
                unit=index,
                stock_operation_id=operation_id,
                occurred_on=paid_on,
                source_month=source,
                posting_month=posting_period,
                physical_quantity=terms.stock_per_sale,
                gross_cents=gross,
                net_cents=gross - tax,
                unit_fee_cents=rules.per_sale_cents,
                loss_cents=0,
                evidence=proofs,
            )
        )
    await db.flush()
    return await posting_read(db, posting)


@router.post(
    PREFIX + "/refunds",
    response_model=PostingRead,
    status_code=201,
    summary="Bestätigte Geldrückzahlung als Partnerkorrektur ohne Warenrücknahme übernehmen",
)
async def recognize_refund(
    venue_id: uuid.UUID, data: RefundInput, user: Actor, db: DB
) -> PostingRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    replay = await posting_replay(db, venue_id, "refund", data)
    if replay:
        return replay
    contract = await contract_for(db, venue_id, data.contract_id)
    cash = (
        await db.execute(
            select(CashEntry).where(
                CashEntry.venue_id == venue_id, CashEntry.id == data.cash_entry_id
            )
        )
    ).scalar_one_or_none()
    if cash is None:
        raise HTTPException(404, "Kassenbeleg nicht gefunden.")
    if (
        cash.kind != "refund"
        or cash.amount_cents >= 0
        or not cash.original_id
        or cash.currency != contract.currency
    ):
        raise HTTPException(
            422, "Eine bestätigte Geldrückzahlung in Vertragswährung ist erforderlich."
        )
    posting = await new_posting(db, contract, user.id, "refund", data)
    found = False
    for allocation in cash.allocations:
        if allocation.get("kind") != "product":
            continue
        line_id, index = uuid.UUID(str(allocation["line_id"])), int(str(allocation["unit"]))
        sale = (
            await db.execute(
                select(PartnerEvent).where(
                    PartnerEvent.contract_id == contract.id,
                    PartnerEvent.order_id == cash.order_id,
                    PartnerEvent.line_id == line_id,
                    PartnerEvent.unit == index,
                    PartnerEvent.kind == "sale",
                )
            )
        ).scalar_one_or_none()
        if sale is None:
            continue
        if not any(str(row.get("cash_entry_id")) == str(cash.original_id) for row in sale.evidence):
            raise HTTPException(
                409, "Rückzahlung verweist nicht auf einen Zahlungsbeleg dieses Partnerverkaufs."
            )
        prior = list(
            (
                await db.execute(
                    select(PartnerEvent).where(
                        PartnerEvent.original_id == sale.id, PartnerEvent.kind == "refund"
                    )
                )
            )
            .scalars()
            .all()
        )
        if any(row.cash_entry_id == cash.id for row in prior):
            raise HTTPException(409, "Diese Geldrückzahlung wurde bereits übernommen.")
        amount, tax = int(str(allocation["amount_cents"])), int(str(allocation["tax_cents"]))
        refunded = -sum(row.gross_cents for row in prior)
        if refunded + amount > sale.gross_cents:
            raise HTTPException(409, "Rückzahlungen übersteigen den ursprünglichen Partnerverkauf.")
        fee_reversal = cents(
            Decimal(sale.unit_fee_cents) * Decimal(refunded + amount) / Decimal(sale.gross_cents)
        ) + sum(row.unit_fee_cents for row in prior)
        db.add(
            PartnerEvent(
                venue_id=venue_id,
                contract_id=contract.id,
                terms_id=sale.terms_id,
                posting_id=posting.id,
                original_id=sale.id,
                cash_entry_id=cash.id,
                order_id=cash.order_id,
                line_id=line_id,
                unit=index,
                kind="refund",
                occurred_on=cash.created_at.astimezone(ZoneInfo(venue.timezone)).date(),
                source_month=sale.source_month,
                posting_month=await posting_month(db, venue, contract, sale.source_month),
                physical_quantity=Decimal(0),
                gross_cents=-amount,
                net_cents=-(amount - tax),
                unit_fee_cents=-fee_reversal,
                loss_cents=0,
                evidence=[
                    {
                        "cash_entry_id": str(cash.id),
                        "original_cash_entry_id": str(cash.original_id),
                        **allocation,
                    }
                ],
            )
        )
        found = True
    if not found:
        raise HTTPException(
            409, "Die Geldrückzahlung enthält keine bereits übernommenen Verkäufe dieses Vertrags."
        )
    await db.flush()
    return await posting_read(db, posting)


@router.post(
    PREFIX + "/stock",
    response_model=PostingRead,
    status_code=201,
    summary="Partnerware an Eigentümer zurückgeben oder Bruch mit Vertragsverantwortung buchen",
)
async def partner_stock(
    venue_id: uuid.UUID, data: PartnerStockInput, user: Actor, db: DB
) -> PostingRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    replay = await posting_replay(db, venue_id, data.kind, data)
    if replay:
        return replay
    contract = await contract_for(db, venue_id, data.contract_id)
    terms = await terms_for(db, contract, today(venue), require_active=False)
    rules = PartnerRules.model_validate(terms.rules)
    lot = await inventory.lot_for(db, venue_id, data.lot_id)
    if lot.owner_id != contract.owner_id or lot.item_id != contract.item_id:
        raise HTTPException(
            422, "Charge und Eigentümer stimmen nicht mit dem Partnervertrag überein."
        )
    kind = cast(OperationKind, data.kind)
    stock_data = BookingInput(
        request_key=uuid.uuid5(data.request_key, "partner-stock"), reason=data.reason
    )
    if await inventory.replay(db, venue_id, kind, stock_data):
        raise HTTPException(409, "Lagerbeleg existiert ohne passende Partnerbuchung.")
    operation = await inventory.post(
        db, venue_id, user.id, kind, stock_data, lot, [(data.location_id, -data.quantity)]
    )
    posting = await new_posting(db, contract, user.id, data.kind, data)
    source = month_of(today(venue))
    loss = 0
    if data.kind == "waste" and rules.loss_responsibility == "venue":
        previous = list(
            (
                await db.execute(
                    select(PartnerEvent).where(
                        PartnerEvent.contract_id == contract.id,
                        PartnerEvent.source_month == source,
                        PartnerEvent.kind == "waste",
                    )
                )
            )
            .scalars()
            .all()
        )
        loss = cents(
            (sum((row.physical_quantity for row in previous), Decimal(0)) + data.quantity)
            * rules.loss_per_stock_unit_cents
        ) - sum(row.loss_cents for row in previous)
    db.add(
        PartnerEvent(
            venue_id=venue_id,
            contract_id=contract.id,
            terms_id=terms.id,
            posting_id=posting.id,
            stock_operation_id=operation.id,
            kind=data.kind,
            occurred_on=today(venue),
            source_month=source,
            posting_month=source,
            physical_quantity=data.quantity,
            gross_cents=0,
            net_cents=0,
            unit_fee_cents=0,
            loss_cents=loss,
            evidence=[],
        )
    )
    await db.flush()
    return await posting_read(db, posting)


async def settlement_preview(db: DB, contract: PartnerContract, month: date) -> SettlementPreview:
    if month.day != 1:
        raise HTTPException(422, "Abrechnungsmonat als Monatsersten angeben.")
    first = (
        await db.execute(
            select(PartnerTerms)
            .where(PartnerTerms.contract_id == contract.id)
            .order_by(PartnerTerms.version)
            .limit(1)
        )
    ).scalar_one()
    previous = list(
        (
            await db.execute(
                select(PartnerSettlement)
                .where(PartnerSettlement.contract_id == contract.id)
                .order_by(PartnerSettlement.month)
            )
        )
        .scalars()
        .all()
    )
    expected = next_month(previous[-1].month) if previous else first.effective_on
    if month != expected:
        raise HTTPException(
            409,
            f"Als Nächstes ist {expected.isoformat()} abzurechnen; abgeschlossene Monate bleiben unverändert.",
        )
    events = list(
        (
            await db.execute(
                select(PartnerEvent)
                .where(PartnerEvent.contract_id == contract.id, PartnerEvent.posting_month <= month)
                .order_by(PartnerEvent.id)
            )
        )
        .scalars()
        .all()
    )
    sources = {month} | {row.source_month for row in events if row.posting_month == month}
    components: list[SettlementComponent] = []
    for source in sorted(sources):
        terms = await terms_for(db, contract, source, require_active=False)
        rules = PartnerRules.model_validate(terms.rules)
        relevant = [row for row in events if row.source_month == source]
        revenue = sum(
            row.net_cents if rules.revenue_basis == "net" else row.gross_cents for row in relevant
        )
        share = cents(
            Decimal(max(0, revenue - rules.revenue_threshold_cents)) * rules.share_bps / 10000
        )
        fees = sum(row.unit_fee_cents for row in relevant)
        fixed = rules.fixed_monthly_cents if terms.active else 0
        topup = (
            max(0, rules.minimum_monthly_cents - (share + fees + fixed))
            if terms.active and rules.minimum_monthly_cents is not None
            else 0
        )
        loss = sum(row.loss_cents for row in relevant)
        calculated = share + fees + fixed + topup + loss
        prior = 0
        for settled in previous:
            snapshot = SettlementPreview.model_validate(settled.snapshot)
            for component in snapshot.components:
                if component.source_month == source:
                    prior += component.delta_cents
        components.append(
            SettlementComponent(
                source_month=source,
                terms_id=terms.id,
                revenue_cents=revenue,
                share_cents=share,
                unit_fees_cents=fees,
                fixed_cents=fixed,
                guarantee_topup_cents=topup,
                loss_cents=loss,
                calculated_payable_cents=calculated,
                previously_settled_cents=prior,
                delta_cents=calculated - prior,
                event_ids=[row.id for row in relevant],
            )
        )
    preview = SettlementPreview(
        contract_id=contract.id,
        month=month,
        currency=contract.currency,
        payable_to_partner_cents=sum(row.delta_cents for row in components),
        components=components,
        fingerprint="",
    )
    preview.fingerprint = svc.digest(preview)
    return preview


@router.get(
    PREFIX + "/contracts/{contract_id}/settlement-preview/{month}",
    response_model=SettlementPreview,
    status_code=200,
    summary="Monatsbetrag samt ursprünglichen und später korrigierten Quellen prüfen",
)
async def preview(
    venue_id: uuid.UUID, contract_id: uuid.UUID, month: date, user: Actor, db: DB
) -> SettlementPreview:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    return await settlement_preview(db, await contract_for(db, venue_id, contract_id), month)


@router.post(
    PREFIX + "/settlements",
    response_model=SettlementRead,
    status_code=201,
    summary="Geprüften vergangenen Monat einmalig und unveränderlich abschließen",
)
async def close_month(
    venue_id: uuid.UUID, data: SettlementInput, user: Actor, db: DB
) -> SettlementRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    previous = (
        await db.execute(
            select(PartnerSettlement).where(
                PartnerSettlement.venue_id == venue_id,
                PartnerSettlement.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if previous:
        if previous.request_hash != svc.digest(data):
            raise HTTPException(
                409, "Vorgangs-ID wurde für einen anderen Monatsabschluss verwendet."
            )
        return SettlementRead.model_validate(previous)
    contract = await contract_for(db, venue_id, data.contract_id)
    if data.month >= month_of(today(venue)):
        raise HTTPException(422, "Nur vollständig vergangene Monate können abgeschlossen werden.")
    await require_complete_sources(db, venue, contract, data.month, user)
    calculated = await settlement_preview(db, contract, data.month)
    if calculated.fingerprint != data.fingerprint:
        raise HTTPException(
            409, "Neue Buchungen haben die Abrechnung verändert. Bitte Vorschau erneut prüfen."
        )
    row = PartnerSettlement(
        venue_id=venue_id,
        contract_id=contract.id,
        month=data.month,
        payable_to_partner_cents=calculated.payable_to_partner_cents,
        snapshot=calculated.model_dump(mode="json"),
        request_key=data.request_key,
        request_hash=svc.digest(data),
        reason=data.reason,
        actor_id=user.id,
    )
    db.add(row)
    await db.flush()
    return SettlementRead.model_validate(row)


async def loan_for(db: DB, venue_id: uuid.UUID, account_id: uuid.UUID) -> LoanAccount:
    row = (
        await db.execute(
            select(LoanAccount).where(
                LoanAccount.venue_id == venue_id, LoanAccount.id == account_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Leihkonto nicht gefunden.")
    return row


async def loan_read(db: DB, account: LoanAccount) -> LoanAccountRead:
    rows = list(
        (
            await db.execute(
                select(LoanEntry)
                .where(LoanEntry.venue_id == account.venue_id, LoanEntry.account_id == account.id)
                .order_by(LoanEntry.created_at, LoanEntry.id)
            )
        )
        .scalars()
        .all()
    )
    quantities = {
        kind: sum(row.quantity for row in rows if row.kind == kind)
        for kind in ("received", "returned", "broken")
    }
    amounts = {
        kind: sum(row.amount_cents for row in rows if row.kind == kind)
        for kind in ("deposit_paid", "deposit_refunded", "deposit_forfeited")
    }
    claim = amounts["deposit_paid"] - amounts["deposit_refunded"] - amounts["deposit_forfeited"]
    return LoanAccountRead(
        id=account.id,
        created_at=account.created_at,
        owner_id=account.owner_id,
        name=account.name,
        reference=account.reference,
        serialized=account.serialized,
        deposit_per_unit_cents=account.deposit_per_unit_cents,
        currency=account.currency,
        physical_quantity=quantities["received"] - quantities["returned"] - quantities["broken"],
        received_quantity=quantities["received"],
        returned_quantity=quantities["returned"],
        broken_quantity=quantities["broken"],
        deposit_claim_cents=claim,
        unpaid_deposit_cents=max(
            0, quantities["received"] * account.deposit_per_unit_cents - amounts["deposit_paid"]
        ),
        refundable_deposit_cents=min(
            claim,
            quantities["returned"] * account.deposit_per_unit_cents - amounts["deposit_refunded"],
        ),
        entries=[LoanEntryRead.model_validate(row) for row in rows],
    )


@router.post(
    PREFIX + "/loans",
    response_model=LoanAccountRead,
    status_code=201,
    summary="Eigenes Leih- und Pfandkonto für Partnerbehälter oder ein nummeriertes Gerät anlegen",
)
async def create_loan(
    venue_id: uuid.UUID, data: LoanAccountInput, user: Actor, db: DB
) -> LoanAccountRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    await owner_for(db, venue_id, data.owner_id)
    if (
        await db.execute(
            select(LoanAccount.id).where(
                LoanAccount.venue_id == venue_id,
                LoanAccount.owner_id == data.owner_id,
                LoanAccount.reference == data.reference,
            )
        )
    ).first():
        raise HTTPException(409, "Diese Leihreferenz besteht für den Partner bereits.")
    row = LoanAccount(venue_id=venue_id, currency=venue.currency, **data.model_dump())
    db.add(row)
    await db.flush()
    return await loan_read(db, row)


@router.post(
    PREFIX + "/loan-entries",
    response_model=LoanAccountRead,
    status_code=201,
    summary="Leihbestand oder belegte Pfandzahlung getrennt buchen",
)
async def loan_entry(
    venue_id: uuid.UUID, data: LoanEntryInput, user: Actor, db: DB
) -> LoanAccountRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    account = await loan_for(db, venue_id, data.account_id)
    previous = (
        await db.execute(
            select(LoanEntry).where(
                LoanEntry.venue_id == venue_id, LoanEntry.request_key == data.request_key
            )
        )
    ).scalar_one_or_none()
    if previous:
        if previous.request_hash != svc.digest(data):
            raise HTTPException(409, "Vorgangs-ID wurde für eine andere Leihbuchung verwendet.")
        return await loan_read(db, account)
    state = await loan_read(db, account)
    if data.kind in {"returned", "broken"} and data.quantity > state.physical_quantity:
        raise HTTPException(409, "Die Stückzahl übersteigt den vorhandenen Leihbestand.")
    if (
        data.kind == "received"
        and account.serialized
        and (data.quantity != 1 or state.physical_quantity or state.broken_quantity)
    ):
        raise HTTPException(
            409, "Ein nummeriertes Gerät darf nur einmal gleichzeitig entgegengenommen werden."
        )
    if data.kind == "deposit_paid" and data.amount_cents > state.unpaid_deposit_cents:
        raise HTTPException(409, "Die Zahlung übersteigt das noch nicht bezahlte Pfand.")
    if data.kind == "deposit_refunded" and data.amount_cents > state.refundable_deposit_cents:
        raise HTTPException(
            409,
            "Pfandrückzahlung übersteigt die bezahlte Forderung für tatsächlich zurückgegebene Gegenstände.",
        )
    if data.kind == "deposit_forfeited":
        forfeited = sum(
            row.amount_cents for row in state.entries if row.kind == "deposit_forfeited"
        )
        available = min(
            state.deposit_claim_cents,
            state.broken_quantity * account.deposit_per_unit_cents - forfeited,
        )
        if data.amount_cents > available:
            raise HTTPException(
                409, "Pfandverfall übersteigt die belegte Verlustmenge oder offene Pfandforderung."
            )
    if data.cash_entry_id:
        cash = (
            await db.execute(
                select(CashEntry).where(
                    CashEntry.venue_id == venue_id, CashEntry.id == data.cash_entry_id
                )
            )
        ).scalar_one_or_none()
        expected = -data.amount_cents if data.kind == "deposit_paid" else data.amount_cents
        if cash is None:
            raise HTTPException(404, "Kassenbeleg nicht gefunden.")
        if (
            cash.kind != "movement"
            or cash.amount_cents != expected
            or cash.currency != account.currency
        ):
            raise HTTPException(
                422,
                "Pfand benötigt eine passende separate Kasseneinlage oder -entnahme, keinen Umsatzbeleg.",
            )
        if (
            await db.execute(
                select(LoanEntry.id).where(
                    LoanEntry.venue_id == venue_id, LoanEntry.cash_entry_id == cash.id
                )
            )
        ).first():
            raise HTTPException(
                409, "Dieser Zahlungsbeleg wurde bereits einem Leihkonto zugeordnet."
            )
    if (
        data.external_reference
        and (
            await db.execute(
                select(LoanEntry.id).where(
                    LoanEntry.venue_id == venue_id,
                    LoanEntry.external_reference == data.external_reference,
                )
            )
        ).first()
    ):
        raise HTTPException(409, "Dieser externe Nachweis wurde bereits verwendet.")
    db.add(
        LoanEntry(
            venue_id=venue_id, actor_id=user.id, request_hash=svc.digest(data), **data.model_dump()
        )
    )
    await db.flush()
    return await loan_read(db, account)


@router.get(
    PREFIX + "/snapshot",
    response_model=PartnerSnapshot,
    status_code=200,
    summary="Verträge, Verkaufsbelege, Abschlüsse und getrennte Leih-/Pfandsalden anzeigen",
)
async def snapshot(venue_id: uuid.UUID, user: Actor, db: DB) -> PartnerSnapshot:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    contracts = (
        (
            await db.execute(
                select(PartnerContract)
                .where(PartnerContract.venue_id == venue_id)
                .order_by(PartnerContract.name)
            )
        )
        .scalars()
        .all()
    )
    events = (
        (
            await db.execute(
                select(PartnerEvent)
                .where(PartnerEvent.venue_id == venue_id)
                .order_by(PartnerEvent.created_at.desc(), PartnerEvent.id)
                .limit(500)
            )
        )
        .scalars()
        .all()
    )
    settlements = (
        (
            await db.execute(
                select(PartnerSettlement)
                .where(PartnerSettlement.venue_id == venue_id)
                .order_by(PartnerSettlement.month.desc())
            )
        )
        .scalars()
        .all()
    )
    loans = (
        (
            await db.execute(
                select(LoanAccount)
                .where(LoanAccount.venue_id == venue_id)
                .order_by(LoanAccount.name)
            )
        )
        .scalars()
        .all()
    )
    return PartnerSnapshot(
        business_date=today(venue),
        contracts=[await contract_read(db, row) for row in contracts],
        events=[EventRead.model_validate(row) for row in events],
        settlements=[SettlementRead.model_validate(row) for row in settlements],
        loans=[await loan_read(db, row) for row in loans],
        unassigned_losses=await loss_candidates(db, venue),
    )


@router.get(
    PREFIX + "/orders/{order_id}/candidates",
    response_model=CandidateRead,
    status_code=200,
    summary="Noch nicht übernommene bezahlte Partnereinheiten und Geldrückzahlungen eines Bons",
)
async def candidates(
    venue_id: uuid.UUID, order_id: uuid.UUID, user: Actor, db: DB
) -> CandidateRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    order = await svc.order_for_venue(db, venue_id, order_id)
    contracts = list(
        (await db.execute(select(PartnerContract).where(PartnerContract.venue_id == venue_id)))
        .scalars()
        .all()
    )
    mapped = {str(contract.menu_item_id): contract for contract in contracts}
    cash_rows = list(
        (
            await db.execute(
                select(CashEntry).where(
                    CashEntry.venue_id == venue_id, CashEntry.order_id == order_id
                )
            )
        )
        .scalars()
        .all()
    )
    existing = list(
        (
            await db.execute(
                select(PartnerEvent).where(
                    PartnerEvent.venue_id == venue_id, PartnerEvent.order_id == order_id
                )
            )
        )
        .scalars()
        .all()
    )
    units = units_for(order, cash_rows, virtual_voucher=False)
    sales: list[SaleCandidate] = []
    refunds: list[RefundCandidate] = []
    notes: list[str] = []
    for line in order.lines:
        contract = mapped.get(str(line.get("item_id")))
        if contract is None or line.get("kind", "product") != "product" or not line.get("line_id"):
            continue
        if line.get("recipe_id"):
            notes.append(
                f"{line['name']}: Rezeptur und direkter Partner-Wiederverkauf dürfen nicht gleichzeitig verbrauchen."
            )
            continue
        if order.fulfillment_status != "served":
            continue
        matching = [
            unit
            for unit in units
            if unit.line_id == str(line["line_id"])
            and not unit.cancelled
            and unit.gross > 0
            and unit.remaining == 0
            and not any(
                row.kind == "sale" and str(row.line_id) == unit.line_id and row.unit == unit.unit
                for row in existing
            )
        ]
        if not matching:
            continue
        try:
            terms = await terms_for(
                db, contract, order.created_at.astimezone(ZoneInfo(venue.timezone)).date()
            )
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            notes.append(f"{line['name']}: Zum Bestelldatum liegt kein aktiver Partnervertrag vor.")
            continue
        sales.append(
            SaleCandidate(
                contract_id=contract.id,
                line_id=uuid.UUID(str(line["line_id"])),
                name=str(line["name"]),
                units=[unit.unit for unit in matching],
                gross_cents=sum(unit.gross for unit in matching),
                stock_quantity=terms.stock_per_sale * len(matching),
            )
        )
    for cash in cash_rows:
        if cash.kind != "refund":
            continue
        by_contract: dict[uuid.UUID, int] = {}
        for allocation in cash.allocations:
            original = next(
                (
                    row
                    for row in existing
                    if row.kind == "sale"
                    and str(row.line_id) == str(allocation["line_id"])
                    and row.unit == int(str(allocation["unit"]))
                ),
                None,
            )
            if original is not None and not any(
                row.kind == "refund"
                and row.original_id == original.id
                and row.cash_entry_id == cash.id
                for row in existing
            ):
                by_contract[original.contract_id] = by_contract.get(original.contract_id, 0) + int(
                    str(allocation["amount_cents"])
                )
        refunds.extend(
            RefundCandidate(contract_id=key, cash_entry_id=cash.id, gross_cents=value)
            for key, value in by_contract.items()
        )
    return CandidateRead(order_id=order.id, sales=sales, refunds=refunds, notes=notes)


async def loss_candidates(db: DB, venue: Venue) -> list[LossCandidate]:
    rows = (
        await db.execute(
            select(StockOperation, StockMovement, StockLot)
            .join(StockMovement, StockMovement.operation_id == StockOperation.id)
            .join(StockLot, StockLot.id == StockMovement.lot_id)
            .join(StockOwner, StockOwner.id == StockLot.owner_id)
            .where(
                StockOperation.venue_id == venue.id,
                StockOperation.kind.in_(["waste", "count"]),
                StockMovement.quantity < 0,
                StockOwner.kind == "partner",
                ~StockOperation.id.in_(
                    select(PartnerEvent.stock_operation_id).where(
                        PartnerEvent.venue_id == venue.id,
                        PartnerEvent.stock_operation_id.is_not(None),
                    )
                ),
            )
            .order_by(StockOperation.created_at, StockOperation.id)
            .limit(500)
        )
    ).all()
    return [
        LossCandidate(
            stock_operation_id=operation.id,
            owner_id=lot.owner_id,
            item_id=lot.item_id,
            quantity=-movement.quantity,
            occurred_on=operation.created_at.astimezone(ZoneInfo(venue.timezone)).date(),
            reason=operation.reason,
        )
        for operation, movement, lot in rows
    ]


@router.post(
    PREFIX + "/losses",
    response_model=PostingRead,
    status_code=201,
    summary="Bestehenden Lagerverlust einem Partnervertrag zuordnen, ohne erneut Bestand zu entnehmen",
)
async def recognize_loss(venue_id: uuid.UUID, data: LossInput, user: Actor, db: DB) -> PostingRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    replay = await posting_replay(db, venue_id, "loss-recognition", data)
    if replay:
        return replay
    contract = await contract_for(db, venue_id, data.contract_id)
    operation = (
        await db.execute(
            select(StockOperation).where(
                StockOperation.venue_id == venue_id, StockOperation.id == data.stock_operation_id
            )
        )
    ).scalar_one_or_none()
    if operation is None:
        raise HTTPException(404, "Lagerbeleg nicht gefunden.")
    if operation.kind not in {"waste", "count"}:
        raise HTTPException(
            422,
            "Nur Schwund und negative Inventurdifferenzen können als Verlust übernommen werden.",
        )
    if (
        await db.execute(
            select(PartnerEvent.id).where(
                PartnerEvent.venue_id == venue_id, PartnerEvent.stock_operation_id == operation.id
            )
        )
    ).first():
        raise HTTPException(409, "Dieser Verlustbeleg wurde bereits einem Vertrag zugeordnet.")
    moves = list(
        (await db.execute(select(StockMovement).where(StockMovement.operation_id == operation.id)))
        .scalars()
        .all()
    )
    if len(moves) != 1 or moves[0].quantity >= 0:
        raise HTTPException(
            422, "Der Verlustbeleg muss genau eine negative Chargenbewegung enthalten."
        )
    lot = await inventory.lot_for(db, venue_id, moves[0].lot_id)
    if lot.owner_id != contract.owner_id or lot.item_id != contract.item_id:
        raise HTTPException(422, "Eigentümer und Lagerartikel passen nicht zum Vertrag.")
    occurred = operation.created_at.astimezone(ZoneInfo(venue.timezone)).date()
    terms = await terms_for(db, contract, occurred, require_active=False)
    rules = PartnerRules.model_validate(terms.rules)
    source = month_of(occurred)
    quantity = -moves[0].quantity
    prior = list(
        (
            await db.execute(
                select(PartnerEvent).where(
                    PartnerEvent.contract_id == contract.id,
                    PartnerEvent.source_month == source,
                    PartnerEvent.kind == "waste",
                )
            )
        )
        .scalars()
        .all()
    )
    loss = 0
    if rules.loss_responsibility == "venue":
        loss = cents(
            (sum((row.physical_quantity for row in prior), Decimal(0)) + quantity)
            * rules.loss_per_stock_unit_cents
        ) - sum(row.loss_cents for row in prior)
    posting = await new_posting(db, contract, user.id, "loss-recognition", data)
    db.add(
        PartnerEvent(
            venue_id=venue_id,
            contract_id=contract.id,
            terms_id=terms.id,
            posting_id=posting.id,
            stock_operation_id=operation.id,
            kind="waste",
            occurred_on=occurred,
            source_month=source,
            posting_month=await posting_month(db, venue, contract, source),
            physical_quantity=quantity,
            gross_cents=0,
            net_cents=0,
            unit_fee_cents=0,
            loss_cents=loss,
            evidence=[
                {
                    "stock_operation_id": str(operation.id),
                    "reason": operation.reason,
                    "kind": operation.kind,
                }
            ],
        )
    )
    await db.flush()
    return await posting_read(db, posting)


async def require_complete_sources(
    db: DB, venue: Venue, contract: PartnerContract, month: date, user: Actor
) -> None:
    end = datetime.combine(next_month(month), datetime.min.time(), ZoneInfo(venue.timezone))
    orders = (
        (
            await db.execute(
                select(Order.id).where(
                    Order.venue_id == venue.id,
                    Order.created_at < end,
                    Order.lines.contains([{"item_id": str(contract.menu_item_id)}]),
                )
            )
        )
        .scalars()
        .all()
    )
    for order_id in orders:
        pending = await candidates(venue.id, order_id, user, db)
        if any(row.contract_id == contract.id for row in pending.sales) or any(
            row.contract_id == contract.id for row in pending.refunds
        ):
            raise HTTPException(
                409,
                "Vor dem Abschluss alle bekannten bezahlten Partnereinheiten und Geldrückzahlungen dieses Vertrags übernehmen.",
            )
    first = (
        await db.execute(
            select(PartnerTerms.effective_on)
            .where(PartnerTerms.contract_id == contract.id)
            .order_by(PartnerTerms.version)
            .limit(1)
        )
    ).scalar_one()
    start = datetime.combine(first, datetime.min.time(), ZoneInfo(venue.timezone))
    unresolved = (
        await db.execute(
            select(StockOperation.id)
            .join(StockMovement, StockMovement.operation_id == StockOperation.id)
            .join(StockLot, StockLot.id == StockMovement.lot_id)
            .where(
                StockOperation.venue_id == venue.id,
                StockOperation.kind.in_(["waste", "count"]),
                StockOperation.created_at >= start,
                StockOperation.created_at < end,
                StockMovement.quantity < 0,
                StockLot.owner_id == contract.owner_id,
                StockLot.item_id == contract.item_id,
                ~StockOperation.id.in_(
                    select(PartnerEvent.stock_operation_id).where(
                        PartnerEvent.stock_operation_id.is_not(None)
                    )
                ),
            )
        )
    ).first()
    if unresolved:
        raise HTTPException(
            409,
            "Vor dem Abschluss alle bekannten Lagerverluste dieser Partnerware einem Vertrag zuordnen.",
        )
