"""Venue-scoped stock workflows with exact quantities and atomic ledger postings."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import JsonValue
from sqlalchemy import func, select

from app.gastro import service as svc
from app.gastro import stock_availability as availability
from app.gastro.inventory_models import (
    StockItem,
    StockLocation,
    StockLot,
    StockMovement,
    StockOperation,
    StockOwner,
)
from app.gastro.inventory_schemas import (
    BalanceRead,
    BookingInput,
    CountInput,
    InventorySnapshot,
    ItemInput,
    ItemRead,
    LocationInput,
    LocationRead,
    LotQuarantineInput,
    LotRead,
    MovementRead,
    OperationKind,
    OperationRead,
    OwnerInput,
    OwnerRead,
    QuarantineInput,
    ReceiptInput,
    TransferInput,
    WasteInput,
)
from app.gastro.models import Venue
from app.gastro.reporting import ReportingDB
from app.gastro.reservation_models import StockReservation, StockReservationClose
from app.gastro.router import DB, Actor, private_response

router = APIRouter(dependencies=[Depends(private_response)])
PREFIX = "/venues/{venue_id}/inventory"


async def item_for(db: DB, venue_id: uuid.UUID, item_id: uuid.UUID) -> StockItem:
    row = (
        await db.execute(
            select(StockItem).where(StockItem.venue_id == venue_id, StockItem.id == item_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Lagerartikel nicht gefunden.")
    return row


async def location_for(db: DB, venue_id: uuid.UUID, location_id: uuid.UUID) -> StockLocation:
    row = (
        await db.execute(
            select(StockLocation).where(
                StockLocation.venue_id == venue_id, StockLocation.id == location_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Lagerort nicht gefunden.")
    return row


async def lot_for(db: DB, venue_id: uuid.UUID, lot_id: uuid.UUID) -> StockLot:
    row = (
        await db.execute(
            select(StockLot).where(StockLot.venue_id == venue_id, StockLot.id == lot_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Charge nicht gefunden.")
    return row


def validate_quantity(item: StockItem, *quantities: Decimal) -> None:
    if item.unit == "piece" and any(quantity % 1 for quantity in quantities):
        raise HTTPException(422, "Dieser Artikel wird in ganzen Stück gebucht.")


async def quantity_at(
    db: DB, venue_id: uuid.UUID, lot_id: uuid.UUID, location_id: uuid.UUID
) -> Decimal:
    amount = (
        await db.execute(
            select(func.coalesce(func.sum(StockMovement.quantity), 0)).where(
                StockMovement.venue_id == venue_id,
                StockMovement.lot_id == lot_id,
                StockMovement.location_id == location_id,
            )
        )
    ).scalar_one()
    return Decimal(str(amount))


async def operation_read(db: DB, operation: StockOperation) -> OperationRead:
    movements = (
        await db.execute(
            select(StockMovement)
            .where(
                StockMovement.venue_id == operation.venue_id,
                StockMovement.operation_id == operation.id,
            )
            .order_by(StockMovement.quantity, StockMovement.id)
        )
    ).scalars()
    return OperationRead(
        id=operation.id,
        created_at=operation.created_at,
        sequence=operation.sequence,
        request_key=operation.request_key,
        kind=cast(OperationKind, operation.kind),
        actor_id=operation.actor_id,
        reason=operation.reason,
        details=operation.details,
        movements=[MovementRead.model_validate(row) for row in movements],
    )


async def replay(
    db: DB, venue_id: uuid.UUID, kind: OperationKind, data: BookingInput
) -> OperationRead | None:
    """Called after the venue lock, shared by all posting endpoints."""
    previous = (
        await db.execute(
            select(StockOperation).where(
                StockOperation.venue_id == venue_id, StockOperation.request_key == data.request_key
            )
        )
    ).scalar_one_or_none()
    if previous is None:
        return None
    if previous.kind != kind or previous.request_hash != svc.digest(data):
        raise HTTPException(
            409, "Diese Vorgangs-ID wurde bereits für eine andere Buchung verwendet."
        )
    return await operation_read(db, previous)


async def post(
    db: DB,
    venue_id: uuid.UUID,
    actor_id: uuid.UUID,
    kind: OperationKind,
    data: BookingInput,
    lot: StockLot,
    deltas: list[tuple[uuid.UUID, Decimal]],
) -> OperationRead:
    return await post_movements(
        db,
        venue_id,
        actor_id,
        kind,
        data,
        [(lot, location_id, quantity) for location_id, quantity in deltas],
        {"lot_id": str(lot.id)},
    )


async def post_movements(
    db: DB,
    venue_id: uuid.UUID,
    actor_id: uuid.UUID,
    kind: OperationKind,
    data: BookingInput,
    entries: list[tuple[StockLot, uuid.UUID, Decimal]],
    details: dict[str, JsonValue] | None = None,
    *,
    reservation_id: uuid.UUID | None = None,
) -> OperationRead:
    """Atomic posting primitive, also usable by future prep and recipe workflows.

    Caller must check venue access, hold its mutation lock and call replay first.
    Entries are grouped by lot/location and all balances are checked before writing.
    """
    deltas: defaultdict[tuple[uuid.UUID, uuid.UUID], Decimal] = defaultdict(Decimal)
    for lot, location_id, quantity in entries:
        if lot.venue_id != venue_id:
            raise HTTPException(404, "Charge nicht gefunden.")
        await location_for(db, venue_id, location_id)
        item = await item_for(db, venue_id, lot.item_id)
        if (
            not quantity.is_finite()
            or abs(quantity) > 999999999
            or quantity != quantity.quantize(Decimal("0.000001"))
        ):
            raise HTTPException(422, "Lagermengen benötigen höchstens sechs Nachkommastellen.")
        validate_quantity(item, quantity)
        deltas[(lot.id, location_id)] += quantity
    reservation: StockReservation | None = None
    if reservation_id is not None:
        reservation = (
            await db.execute(
                select(StockReservation).where(
                    StockReservation.venue_id == venue_id, StockReservation.id == reservation_id
                )
            )
        ).scalar_one_or_none()
        if reservation is None:
            raise HTTPException(404, "Reservierung nicht gefunden.")
        now = availability.utc_now()
        if (
            kind != "consume"
            or reservation.expires_at <= now
            or deltas != {(reservation.lot_id, reservation.location_id): -reservation.quantity}
            or (
                await db.execute(
                    select(StockReservationClose.id).where(
                        StockReservationClose.reservation_id == reservation.id
                    )
                )
            ).first()
            or await availability.covered_quantity(db, reservation, now=now) < reservation.quantity
        ):
            raise HTTPException(
                409,
                "Reservierter Verbrauch benötigt genau die vollständig gedeckte, aktive Reservierung.",
            )
        lot = await lot_for(db, venue_id, reservation.lot_id)
        owner_kind = (
            await db.execute(select(StockOwner.kind).where(StockOwner.id == lot.owner_id))
        ).scalar_one()
        timezone = (
            await db.execute(select(Venue.timezone).where(Venue.id == venue_id))
        ).scalar_one()
        usage = (details or {}).get("usage_reference")
        if (
            owner_kind != "own"
            or lot.blocked
            or (
                lot.expires_on is not None
                and lot.expires_on < now.astimezone(ZoneInfo(timezone)).date()
            )
            or not isinstance(usage, str)
            or len(usage.strip()) < 3
        ):
            raise HTTPException(
                409,
                "Reservierter manueller Verbrauch benötigt freigegebene, haltbare Eigenware und einen konkreten Verbrauchsbeleg.",
            )
    shortfalls: list[JsonValue] = []
    for (lot_id, location_id), quantity in deltas.items():
        physical = await quantity_at(db, venue_id, lot_id, location_id)
        if quantity < 0 and physical < -quantity:
            raise HTTPException(409, "Die Buchung würde den Chargenbestand unterschreiten.")
        held = await availability.reserved_at(db, venue_id, lot_id, location_id)
        if quantity < 0 and kind != "count" and reservation is None and physical - held < -quantity:
            raise HTTPException(
                409,
                "Die Buchung würde eine aktive Lagerreservierung verbrauchen. Reservierung vorher prüfen oder freigeben.",
            )
        if kind == "count" and held > physical + quantity:
            shortfalls.append(
                {
                    "lot_id": str(lot_id),
                    "location_id": str(location_id),
                    "reserved_quantity": str(held),
                    "physical_quantity": str(physical + quantity),
                    "shortfall_quantity": str(held - physical - quantity),
                }
            )
    operation = StockOperation(
        venue_id=venue_id,
        request_key=data.request_key,
        request_hash=svc.digest(data),
        kind=kind,
        actor_id=actor_id,
        reason=data.reason,
        details={
            **data.model_dump(mode="json"),
            **(details or {}),
            **({"reservation_shortfalls": shortfalls} if shortfalls else {}),
        },
    )
    db.add(operation)
    await db.flush()
    for (lot_id, location_id), quantity in deltas.items():
        if quantity:
            db.add(
                StockMovement(
                    venue_id=venue_id,
                    operation_id=operation.id,
                    lot_id=lot_id,
                    location_id=location_id,
                    quantity=quantity,
                )
            )
    lot_ids: list[JsonValue] = [str(lot_id) for lot_id in sorted({lot_id for lot_id, _ in deltas})]
    if reservation is not None:
        db.add(
            StockReservationClose(
                venue_id=venue_id,
                reservation_id=reservation.id,
                kind="consume",
                stock_operation_id=operation.id,
                request_key=data.request_key,
                request_hash=svc.digest(data),
                reason=data.reason,
                actor_id=actor_id,
            )
        )
    svc.event(
        db,
        venue_id,
        f"inventory.{kind}_posted",
        operation.id,
        {"lot_ids": lot_ids},
        actor_id,
    )
    await db.flush()
    return await operation_read(db, operation)


@router.get(
    PREFIX + "/snapshot",
    response_model=InventorySnapshot,
    status_code=200,
    summary="Lagerartikel, Eigentümer, Chargen und genaue Bestände dieses Betriebs",
)
async def snapshot(venue_id: uuid.UUID, db: ReportingDB, user: Actor) -> InventorySnapshot:
    # ReportingDB establishes a consistent read-only snapshot before authentication.
    venue, _ = await svc.venue_access(db, user, venue_id)
    today = datetime.now(ZoneInfo(venue.timezone)).date()
    items = (
        (
            await db.execute(
                select(StockItem).where(StockItem.venue_id == venue_id).order_by(StockItem.sku)
            )
        )
        .scalars()
        .all()
    )
    owners = (
        (
            await db.execute(
                select(StockOwner).where(StockOwner.venue_id == venue_id).order_by(StockOwner.name)
            )
        )
        .scalars()
        .all()
    )
    locations = (
        (
            await db.execute(
                select(StockLocation)
                .where(StockLocation.venue_id == venue_id)
                .order_by(StockLocation.name)
            )
        )
        .scalars()
        .all()
    )
    lots = (
        (
            await db.execute(
                select(StockLot)
                .where(StockLot.venue_id == venue_id)
                .order_by(StockLot.expires_on.asc().nulls_last(), StockLot.code)
            )
        )
        .scalars()
        .all()
    )
    lot_index = {lot.id: lot for lot in lots}
    quantities = (
        await db.execute(
            select(
                StockMovement.lot_id, StockMovement.location_id, func.sum(StockMovement.quantity)
            )
            .where(StockMovement.venue_id == venue_id)
            .group_by(StockMovement.lot_id, StockMovement.location_id)
            .order_by(StockMovement.lot_id, StockMovement.location_id)
        )
    ).all()
    balances = []
    for lot_id, location_id, amount in quantities:
        lot = lot_index[lot_id]
        expired = lot.expires_on is not None and lot.expires_on < today
        quantity = Decimal(str(amount))
        reserved = await availability.reserved_at(db, venue_id, lot_id, location_id)
        balances.append(
            BalanceRead(
                lot_id=lot.id,
                item_id=lot.item_id,
                owner_id=lot.owner_id,
                location_id=location_id,
                quantity=quantity,
                expires_on=lot.expires_on,
                expired=expired,
                blocked=lot.blocked,
                available_quantity=(
                    Decimal(0) if lot.blocked or expired else max(Decimal(0), quantity - reserved)
                ),
                reserved_quantity=reserved,
                reservation_shortfall_quantity=max(Decimal(0), reserved - quantity),
            )
        )
    return InventorySnapshot(
        business_date=today,
        items=[ItemRead.model_validate(row) for row in items],
        owners=[OwnerRead.model_validate(row) for row in owners],
        locations=[LocationRead.model_validate(row) for row in locations],
        lots=[LotRead.model_validate(row) for row in lots],
        balances=balances,
    )


@router.post(
    PREFIX + "/items", response_model=ItemRead, status_code=201, summary="Lagerartikel anlegen"
)
async def create_item(venue_id: uuid.UUID, data: ItemInput, user: Actor, db: DB) -> StockItem:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    if (
        await db.execute(
            select(StockItem.id).where(StockItem.venue_id == venue_id, StockItem.sku == data.sku)
        )
    ).first():
        raise HTTPException(409, "Diese Lagernummer ist bereits vergeben.")
    row = StockItem(venue_id=venue_id, **data.model_dump())
    db.add(row)
    await db.flush()
    svc.event(db, venue_id, "inventory.item_created", row.id, {"sku": row.sku}, user.id)
    return row


@router.post(
    PREFIX + "/owners", response_model=OwnerRead, status_code=201, summary="Wareneigentümer anlegen"
)
async def create_owner(venue_id: uuid.UUID, data: OwnerInput, user: Actor, db: DB) -> StockOwner:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    if (
        await db.execute(
            select(StockOwner.id).where(
                StockOwner.venue_id == venue_id, StockOwner.name == data.name
            )
        )
    ).first():
        raise HTTPException(409, "Dieser Eigentümer ist bereits erfasst.")
    row = StockOwner(venue_id=venue_id, **data.model_dump())
    db.add(row)
    await db.flush()
    svc.event(db, venue_id, "inventory.owner_created", row.id, {"kind": row.kind}, user.id)
    return row


@router.post(
    PREFIX + "/locations", response_model=LocationRead, status_code=201, summary="Lagerort anlegen"
)
async def create_location(
    venue_id: uuid.UUID, data: LocationInput, user: Actor, db: DB
) -> StockLocation:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    if (
        await db.execute(
            select(StockLocation.id).where(
                StockLocation.venue_id == venue_id, StockLocation.name == data.name
            )
        )
    ).first():
        raise HTTPException(409, "Dieser Lagerort ist bereits erfasst.")
    row = StockLocation(venue_id=venue_id, **data.model_dump())
    db.add(row)
    await db.flush()
    svc.event(db, venue_id, "inventory.location_created", row.id, {}, user.id)
    return row


@router.post(
    PREFIX + "/receipts",
    response_model=OperationRead,
    status_code=201,
    summary="Wareneingang mit Charge und Eigentümer genau einmal buchen",
)
async def receive(venue_id: uuid.UUID, data: ReceiptInput, user: Actor, db: DB) -> OperationRead:
    await svc.venue_access(db, user, venue_id, svc.KITCHEN, lock=True)
    previous = await replay(db, venue_id, "receipt", data)
    if previous is not None:
        return previous
    item = await item_for(db, venue_id, data.item_id)
    await location_for(db, venue_id, data.location_id)
    owner = (
        await db.execute(
            select(StockOwner).where(
                StockOwner.venue_id == venue_id, StockOwner.id == data.owner_id
            )
        )
    ).scalar_one_or_none()
    if owner is None:
        raise HTTPException(404, "Eigentümer nicht gefunden.")
    validate_quantity(item, data.quantity)
    if item.requires_expiry and data.expires_on is None:
        raise HTTPException(422, "Für diesen Artikel ist das MHD erforderlich.")
    lot = (
        await db.execute(
            select(StockLot).where(
                StockLot.venue_id == venue_id,
                StockLot.item_id == item.id,
                StockLot.owner_id == owner.id,
                StockLot.code == data.lot_code,
            )
        )
    ).scalar_one_or_none()
    if lot is None:
        lot = StockLot(
            venue_id=venue_id,
            item_id=item.id,
            owner_id=owner.id,
            code=data.lot_code,
            expires_on=data.expires_on,
            blocked=data.blocked,
        )
        db.add(lot)
        await db.flush()
    elif lot.expires_on != data.expires_on:
        raise HTTPException(
            409, "Diese Charge hat bereits ein anderes MHD. Bitte die Liefercharge prüfen."
        )
    elif lot.blocked != data.blocked:
        raise HTTPException(
            409,
            "Die Charge hat einen anderen Quarantänestand. Bitte den bestehenden Chargenstand übernehmen.",
        )
    return await post(
        db, venue_id, user.id, "receipt", data, lot, [(data.location_id, data.quantity)]
    )


@router.post(
    PREFIX + "/lots/{lot_id}/quarantine",
    response_model=OperationRead,
    status_code=201,
    summary="Charge sperren oder durch die Betriebsleitung wieder freigeben",
)
async def quarantine(
    venue_id: uuid.UUID, lot_id: uuid.UUID, data: QuarantineInput, user: Actor, db: DB
) -> OperationRead:
    _, role = await svc.venue_access(db, user, venue_id, svc.KITCHEN, lock=True)
    if not data.blocked and role != "manager":
        raise HTTPException(403, "Nur die Betriebsleitung darf eine Charge wieder freigeben.")
    # The target is part of the request fingerprint, including on a replay.
    fingerprint_data = LotQuarantineInput(**data.model_dump(), lot_id=lot_id)
    previous = await replay(db, venue_id, "quarantine", fingerprint_data)
    if previous is not None:
        return previous
    lot = await lot_for(db, venue_id, lot_id)
    svc.check_version(lot.version, data.version)
    lot.blocked = data.blocked
    lot.version += 1
    return await post(db, venue_id, user.id, "quarantine", fingerprint_data, lot, [])


@router.post(
    PREFIX + "/transfers",
    response_model=OperationRead,
    status_code=201,
    summary="Ware atomar zwischen zwei Lagerorten umlagern",
)
async def transfer(venue_id: uuid.UUID, data: TransferInput, user: Actor, db: DB) -> OperationRead:
    await svc.venue_access(db, user, venue_id, svc.KITCHEN, lock=True)
    previous = await replay(db, venue_id, "transfer", data)
    if previous is not None:
        return previous
    lot = await lot_for(db, venue_id, data.lot_id)
    await location_for(db, venue_id, data.source_location_id)
    await location_for(db, venue_id, data.destination_location_id)
    validate_quantity(await item_for(db, venue_id, lot.item_id), data.quantity)
    available = await quantity_at(db, venue_id, lot.id, data.source_location_id)
    if data.quantity > available:
        raise HTTPException(409, "Die Menge übersteigt den Bestand dieser Charge am Quellort.")
    return await post(
        db,
        venue_id,
        user.id,
        "transfer",
        data,
        lot,
        [(data.source_location_id, -data.quantity), (data.destination_location_id, data.quantity)],
    )


@router.post(
    PREFIX + "/waste",
    response_model=OperationRead,
    status_code=201,
    summary="Schwund mit Charge, Menge und Begründung festhalten",
)
async def waste(venue_id: uuid.UUID, data: WasteInput, user: Actor, db: DB) -> OperationRead:
    await svc.venue_access(db, user, venue_id, svc.KITCHEN, lock=True)
    previous = await replay(db, venue_id, "waste", data)
    if previous is not None:
        return previous
    lot = await lot_for(db, venue_id, data.lot_id)
    await location_for(db, venue_id, data.location_id)
    validate_quantity(await item_for(db, venue_id, lot.item_id), data.quantity)
    available = await quantity_at(db, venue_id, lot.id, data.location_id)
    if data.quantity > available:
        raise HTTPException(
            409, "Die Schwundmenge übersteigt den Bestand dieser Charge am Lagerort."
        )
    return await post(
        db, venue_id, user.id, "waste", data, lot, [(data.location_id, -data.quantity)]
    )


@router.post(
    PREFIX + "/counts",
    response_model=OperationRead,
    status_code=201,
    summary="Gezählten Bestand prüfen und nur die Inventurdifferenz buchen",
)
async def count(venue_id: uuid.UUID, data: CountInput, user: Actor, db: DB) -> OperationRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    previous = await replay(db, venue_id, "count", data)
    if previous is not None:
        return previous
    lot = await lot_for(db, venue_id, data.lot_id)
    await location_for(db, venue_id, data.location_id)
    validate_quantity(
        await item_for(db, venue_id, lot.item_id), data.counted_quantity, data.expected_quantity
    )
    available = await quantity_at(db, venue_id, lot.id, data.location_id)
    if available != data.expected_quantity:
        raise HTTPException(
            409, "Seit dem Laden wurde hier gebucht. Bestand neu laden und Zählung erneut prüfen."
        )
    return await post(
        db,
        venue_id,
        user.id,
        "count",
        data,
        lot,
        [(data.location_id, data.counted_quantity - available)],
    )


@router.get(
    PREFIX + "/operations",
    response_model=list[OperationRead],
    status_code=200,
    summary="Unveränderliche Lagerbuchungen mit fortlaufendem Cursor lesen",
)
async def operations(
    venue_id: uuid.UUID,
    user: Actor,
    db: DB,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[OperationRead]:
    await svc.venue_access(db, user, venue_id)
    rows = (
        (
            await db.execute(
                select(StockOperation)
                .where(StockOperation.venue_id == venue_id, StockOperation.sequence > after)
                .order_by(StockOperation.sequence)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [await operation_read(db, row) for row in rows]
