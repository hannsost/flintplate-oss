"""Exact holds, honest inventory shortfalls, release and referenced manual consumption."""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.gastro import inventory
from app.gastro import service as svc
from app.gastro import stock_availability as availability
from app.gastro.inventory_models import StockOwner
from app.gastro.models import Venue
from app.gastro.reservation_models import StockReservation, StockReservationClose
from app.gastro.reservation_schemas import (
    ReservationCloseInput,
    ReservationInput,
    ReservationRead,
    ReservationStatus,
    ScopedReservationCloseInput,
)
from app.gastro.router import DB, Actor, private_response

router = APIRouter(dependencies=[Depends(private_response)])
PREFIX = "/venues/{venue_id}/inventory/reservations"


async def reservation_for(
    db: DB, venue_id: uuid.UUID, reservation_id: uuid.UUID
) -> StockReservation:
    row = (
        await db.execute(
            select(StockReservation).where(
                StockReservation.venue_id == venue_id, StockReservation.id == reservation_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Reservierung nicht gefunden.")
    return row


async def reservation_read(db: DB, venue: Venue, row: StockReservation) -> ReservationRead:
    closure = (
        await db.execute(
            select(StockReservationClose).where(
                StockReservationClose.venue_id == venue.id,
                StockReservationClose.reservation_id == row.id,
            )
        )
    ).scalar_one_or_none()
    now = availability.utc_now()
    covered = await availability.covered_quantity(db, row, now=now)
    lot = await inventory.lot_for(db, venue.id, row.lot_id)
    owner = (
        await db.execute(
            select(StockOwner).where(StockOwner.id == lot.owner_id, StockOwner.venue_id == venue.id)
        )
    ).scalar_one()
    expired = (
        lot.expires_on is not None
        and lot.expires_on < now.astimezone(ZoneInfo(venue.timezone)).date()
    )
    if closure:
        status = "released" if closure.kind == "release" else "consumed"
    elif row.expires_at <= now:
        status = "expired"
    elif covered < row.quantity:
        status = "undercovered"
    else:
        status = "active"
    return ReservationRead(
        id=row.id,
        created_at=row.created_at,
        lot_id=row.lot_id,
        location_id=row.location_id,
        quantity=row.quantity,
        expires_at=row.expires_at,
        actor_id=row.actor_id,
        reason=row.reason,
        status=cast(ReservationStatus, status),
        covered_quantity=covered,
        shortfall_quantity=(
            row.quantity - covered if status in {"active", "undercovered"} else Decimal(0)
        ),
        blocked=lot.blocked,
        lot_expired=expired,
        consumable=status == "active" and not lot.blocked and not expired and owner.kind == "own",
        closure_id=closure.id if closure else None,
        stock_operation_id=closure.stock_operation_id if closure else None,
        closed_at=closure.created_at if closure else None,
        closed_by=closure.actor_id if closure else None,
        closure_reason=closure.reason if closure else "",
    )


@router.get(
    PREFIX,
    response_model=list[ReservationRead],
    status_code=200,
    summary="Lagerreservierungen mit tatsächlicher Deckung und unveränderlichen Abschlussbelegen",
)
async def list_reservations(venue_id: uuid.UUID, user: Actor, db: DB) -> list[ReservationRead]:
    venue, _ = await svc.venue_access(db, user, venue_id, lock=True)
    rows = (
        (
            await db.execute(
                select(StockReservation)
                .where(StockReservation.venue_id == venue_id)
                .order_by(StockReservation.created_at.desc(), StockReservation.id)
                .limit(500)
            )
        )
        .scalars()
        .all()
    )
    return [await reservation_read(db, venue, row) for row in rows]


@router.post(
    PREFIX,
    response_model=ReservationRead,
    status_code=201,
    summary="Freigegebene genaue Chargenmenge befristet für einen konkreten Zweck reservieren",
)
async def reserve(
    venue_id: uuid.UUID, data: ReservationInput, user: Actor, db: DB
) -> ReservationRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.KITCHEN, lock=True)
    previous = (
        await db.execute(
            select(StockReservation).where(
                StockReservation.venue_id == venue_id,
                StockReservation.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if previous:
        if previous.request_hash != svc.digest(data):
            raise HTTPException(409, "Vorgangs-ID wurde für eine andere Reservierung verwendet.")
        return await reservation_read(db, venue, previous)
    lot = await inventory.lot_for(db, venue_id, data.lot_id)
    await inventory.location_for(db, venue_id, data.location_id)
    inventory.validate_quantity(await inventory.item_for(db, venue_id, lot.item_id), data.quantity)
    now = availability.utc_now()
    expires_at = now + timedelta(minutes=data.duration_minutes)
    if lot.blocked or (
        lot.expires_on is not None
        and lot.expires_on < now.astimezone(ZoneInfo(venue.timezone)).date()
    ):
        raise HTTPException(409, "Gesperrte oder abgelaufene Ware kann nicht reserviert werden.")
    if lot.expires_on is not None and expires_at >= datetime.combine(
        lot.expires_on + timedelta(days=1), time.min, ZoneInfo(venue.timezone)
    ):
        raise HTTPException(
            422, "Die Reservierung darf nicht über das Mindesthaltbarkeitsdatum hinausgehen."
        )
    if data.quantity > await availability.available_at(db, venue_id, lot.id, data.location_id):
        raise HTTPException(
            409, "Die Menge übersteigt den nach bestehenden Reservierungen freien Bestand."
        )
    row = StockReservation(
        created_at=now,
        venue_id=venue_id,
        lot_id=lot.id,
        location_id=data.location_id,
        quantity=data.quantity,
        expires_at=expires_at,
        actor_id=user.id,
        reason=data.reason,
        request_key=data.request_key,
        request_hash=svc.digest(data),
    )
    db.add(row)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "inventory.reserved",
        row.id,
        {
            "lot_id": str(lot.id),
            "quantity": str(data.quantity),
            "expires_at": expires_at.isoformat(),
        },
        user.id,
    )
    return await reservation_read(db, venue, row)


@router.post(
    PREFIX + "/{reservation_id}/close",
    response_model=ReservationRead,
    status_code=201,
    summary="Reservierung freigeben oder vollständig gedeckte Eigenware mit Verbrauchsreferenz genau einmal entnehmen",
)
async def close_reservation(
    venue_id: uuid.UUID, reservation_id: uuid.UUID, data: ReservationCloseInput, user: Actor, db: DB
) -> ReservationRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.KITCHEN, lock=True)
    row = await reservation_for(db, venue_id, reservation_id)
    scoped = ScopedReservationCloseInput(reservation_id=reservation_id, **data.model_dump())
    previous = (
        await db.execute(
            select(StockReservationClose).where(
                StockReservationClose.venue_id == venue_id,
                StockReservationClose.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if previous:
        if previous.request_hash != svc.digest(scoped):
            raise HTTPException(
                409, "Vorgangs-ID wurde für einen anderen Reservierungsabschluss verwendet."
            )
        return await reservation_read(db, venue, row)
    if (
        await db.execute(
            select(StockReservationClose.id).where(StockReservationClose.reservation_id == row.id)
        )
    ).first():
        raise HTTPException(409, "Diese Reservierung wurde bereits abgeschlossen.")
    state = await reservation_read(db, venue, row)
    if data.kind == "consume":
        if not data.usage_reference or len(data.usage_reference) < 3:
            raise HTTPException(
                422,
                "Manueller Lagerverbrauch benötigt eine konkrete Produktions- oder Verbrauchsreferenz.",
            )
        if not state.consumable:
            raise HTTPException(
                409,
                "Nur vollständig gedeckte, gültige und freigegebene Reservierungen von Eigenware können manuell verbraucht werden. Partnerware nach Freigabe über den belegten Verkauf oder Partnerverlust buchen.",
            )
        lot = await inventory.lot_for(db, venue_id, row.lot_id)
        if await inventory.replay(db, venue_id, "consume", scoped):
            raise HTTPException(
                409, "Verbrauchsbeleg existiert ohne passenden Reservierungsabschluss."
            )
        # post_movements validates the hold again and inserts its matching closure atomically.
        await inventory.post_movements(
            db,
            venue_id,
            user.id,
            "consume",
            scoped,
            [(lot, row.location_id, -row.quantity)],
            {
                "source": "manual_reserved_consumption",
                "usage_reference": data.usage_reference,
                "reservation_id": str(row.id),
            },
            reservation_id=row.id,
        )
    else:
        db.add(
            StockReservationClose(
                venue_id=venue_id,
                reservation_id=row.id,
                kind="release",
                stock_operation_id=None,
                actor_id=user.id,
                reason=data.reason,
                request_key=data.request_key,
                request_hash=svc.digest(scoped),
            )
        )
        await db.flush()
    svc.event(
        db,
        venue_id,
        "inventory.reservation_closed",
        row.id,
        {"kind": data.kind, "usage_reference": data.usage_reference},
        user.id,
    )
    return await reservation_read(db, venue, row)
