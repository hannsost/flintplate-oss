"""Physical counting stays authoritative; reservation coverage is a derived view."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.inventory_models import StockMovement
from app.gastro.reservation_models import StockReservation, StockReservationClose


def utc_now() -> datetime:
    return datetime.now(UTC)


async def active_holds(
    db: AsyncSession,
    venue_id: uuid.UUID,
    lot_id: uuid.UUID,
    location_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> list[StockReservation]:
    return list(
        (
            await db.execute(
                select(StockReservation)
                .where(
                    StockReservation.venue_id == venue_id,
                    StockReservation.lot_id == lot_id,
                    StockReservation.location_id == location_id,
                    StockReservation.expires_at > (now or utc_now()),
                    ~StockReservation.id.in_(
                        select(StockReservationClose.reservation_id).where(
                            StockReservationClose.venue_id == venue_id
                        )
                    ),
                )
                .order_by(StockReservation.created_at, StockReservation.id)
            )
        )
        .scalars()
        .all()
    )


async def reserved_at(
    db: AsyncSession,
    venue_id: uuid.UUID,
    lot_id: uuid.UUID,
    location_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> Decimal:
    return sum(
        (row.quantity for row in await active_holds(db, venue_id, lot_id, location_id, now=now)),
        Decimal(0),
    )


async def physical_at(
    db: AsyncSession, venue_id: uuid.UUID, lot_id: uuid.UUID, location_id: uuid.UUID
) -> Decimal:
    quantity = (
        await db.execute(
            select(func.coalesce(func.sum(StockMovement.quantity), 0)).where(
                StockMovement.venue_id == venue_id,
                StockMovement.lot_id == lot_id,
                StockMovement.location_id == location_id,
            )
        )
    ).scalar_one()
    return Decimal(str(quantity))


async def available_at(
    db: AsyncSession, venue_id: uuid.UUID, lot_id: uuid.UUID, location_id: uuid.UUID
) -> Decimal:
    return max(
        Decimal(0),
        await physical_at(db, venue_id, lot_id, location_id)
        - await reserved_at(db, venue_id, lot_id, location_id),
    )


async def covered_quantity(
    db: AsyncSession, reservation: StockReservation, *, now: datetime | None = None
) -> Decimal:
    remaining = await physical_at(
        db, reservation.venue_id, reservation.lot_id, reservation.location_id
    )
    for row in await active_holds(
        db, reservation.venue_id, reservation.lot_id, reservation.location_id, now=now
    ):
        if row.id == reservation.id:
            return min(row.quantity, max(Decimal(0), remaining))
        remaining -= row.quantity
    return Decimal(0)
