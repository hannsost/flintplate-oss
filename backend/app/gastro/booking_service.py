"""Shared physical-resource rules for service, guest booking and activities."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.gastro.booking_models import ReservationMeta, ReservationResource
from app.gastro.booking_schemas import GroupRead
from app.gastro.models import DiningTable, Order, Reservation, UsageSession
from app.gastro.schemas import ReservationRead
from app.gastro.service_models import GuestTab, ServiceVisit


def uses_resource(table_id: uuid.UUID) -> ColumnElement[bool]:
    return or_(
        Reservation.table_id == table_id,
        select(ReservationResource.id)
        .where(
            ReservationResource.reservation_id == Reservation.id,
            ReservationResource.table_id == table_id,
        )
        .exists(),
    )


async def table_ids_for(db: AsyncSession, reservation: Reservation) -> list[uuid.UUID]:
    linked = list(
        (
            await db.execute(
                select(ReservationResource.table_id)
                .where(ReservationResource.reservation_id == reservation.id)
                .order_by(ReservationResource.position)
            )
        ).scalars()
    )
    return list(dict.fromkeys([reservation.table_id, *linked]))


async def group_reads(db: AsyncSession, rows: list[Reservation]) -> list[GroupRead]:
    if not rows:
        return []
    ids = [row.id for row in rows]
    metadata = {
        row.reservation_id: row
        for row in (
            await db.execute(select(ReservationMeta).where(ReservationMeta.reservation_id.in_(ids)))
        ).scalars()
    }
    table_ids = {row.id: [row.table_id] for row in rows}
    resources = (
        await db.execute(
            select(ReservationResource)
            .where(ReservationResource.reservation_id.in_(ids))
            .order_by(ReservationResource.position)
        )
    ).scalars()
    for link in resources:
        if link.table_id not in table_ids[link.reservation_id]:
            table_ids[link.reservation_id].append(link.table_id)
    return [
        GroupRead(
            **ReservationRead.model_validate(row).model_dump(),
            table_ids=table_ids[row.id],
            source=metadata[row.id].source if row.id in metadata else "reservation",
            note=metadata[row.id].note if row.id in metadata else "",
            checked_in_at=metadata[row.id].checked_in_at if row.id in metadata else None,
            closed_at=metadata[row.id].closed_at if row.id in metadata else None,
        )
        for row in rows
    ]


async def group_read(db: AsyncSession, row: Reservation) -> GroupRead:
    return (await group_reads(db, [row]))[0]


async def lock_resources(
    db: AsyncSession, venue_id: uuid.UUID, table_ids: list[uuid.UUID]
) -> list[DiningTable]:
    # All callers acquire physical rows in this order, even if the display's
    # primary table is different. This also serializes with legacy single bookings.
    ids = sorted(set(table_ids))
    rows = list(
        (
            await db.execute(
                select(DiningTable)
                .where(DiningTable.venue_id == venue_id, DiningTable.id.in_(ids))
                .order_by(DiningTable.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalars()
    )
    if len(rows) != len(ids):
        raise HTTPException(404, "Eine Ressource gehört nicht zu diesem Betrieb.")
    return rows


async def lock_group(
    db: AsyncSession, venue_id: uuid.UUID, reservation_id: uuid.UUID
) -> Reservation:
    row = (
        await db.execute(
            select(Reservation).where(
                Reservation.id == reservation_id, Reservation.venue_id == venue_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Reservierung nicht gefunden.")
    await lock_resources(db, venue_id, await table_ids_for(db, row))
    return (
        await db.execute(
            select(Reservation)
            .where(Reservation.id == reservation_id, Reservation.venue_id == venue_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def conflicting_resources(
    db: AsyncSession,
    table_ids: list[uuid.UUID],
    start: datetime,
    end: datetime,
    *,
    exclude_reservation_id: uuid.UUID | None = None,
    live: bool = False,
    ignore_order_occupancy: bool = False,
) -> set[uuid.UUID]:
    """Planning uses booked intervals; admission rechecks actual live occupancy.

    An overdue seated group may not disappear during admission merely because
    its planned end passed. It also must not block a reservation weeks later.
    """
    if not table_ids:
        return set()
    overlap = and_(Reservation.starts_at < end, Reservation.ends_at > start)
    if live:
        overlap = or_(overlap, Reservation.status == "seated")
    query = (
        select(Reservation.table_id, ReservationResource.table_id)
        .outerjoin(ReservationResource, ReservationResource.reservation_id == Reservation.id)
        .where(
            Reservation.status.in_(["confirmed", "seated"]),
            overlap,
            or_(Reservation.table_id.in_(table_ids), ReservationResource.table_id.in_(table_ids)),
        )
    )
    if exclude_reservation_id is not None:
        query = query.where(Reservation.id != exclude_reservation_id)
    blocked: set[uuid.UUID] = set()
    requested = set(table_ids)
    for primary, linked in (await db.execute(query)).all():
        if primary in requested:
            blocked.add(primary)
        if linked in requested:
            blocked.add(linked)
    usage_query = select(UsageSession.table_id).where(
        UsageSession.table_id.in_(table_ids), UsageSession.ends_at.is_(None)
    )
    if not live:
        usage_query = usage_query.where(
            UsageSession.starts_at < end, UsageSession.reserved_until > start
        )
    blocked.update((await db.execute(usage_query)).scalars())
    if live and not ignore_order_occupancy:
        # Legacy restaurant bills imply presence. Visit-backed bills keep their
        # original table as evidence; current presence follows the guest tab,
        # including after payment and after moving to another table.
        occupied_orders = (
            await db.execute(
                select(Order.id, Order.venue_id, Order.table_id)
                .join(DiningTable, DiningTable.id == Order.table_id)
                .where(
                    Order.table_id.in_(table_ids),
                    DiningTable.kind == "table",
                    Order.status.in_(["sent", "preparing", "ready", "served"]),
                )
            )
        ).all()
        from app.gastro.service_contexts import context_bound_order_ids

        venue_orders: dict[uuid.UUID, list[uuid.UUID]] = {}
        for order_id, venue_id, _ in occupied_orders:
            venue_orders.setdefault(venue_id, []).append(order_id)
        contextual: set[uuid.UUID] = set()
        for venue_id, order_ids in venue_orders.items():
            contextual.update(await context_bound_order_ids(db, venue_id, order_ids))
        blocked.update(
            table_id
            for order_id, _, table_id in occupied_orders
            if table_id is not None and order_id not in contextual
        )
        present_tables = (
            await db.execute(
                select(GuestTab.current_table_id)
                .join(ServiceVisit, ServiceVisit.id == GuestTab.visit_id)
                .join(DiningTable, DiningTable.id == GuestTab.current_table_id)
                .where(
                    GuestTab.current_table_id.in_(table_ids),
                    GuestTab.present.is_(True),
                    GuestTab.kind == "guest",
                    ServiceVisit.ended_at.is_(None),
                    ServiceVisit.venue_id == GuestTab.venue_id,
                    DiningTable.venue_id == GuestTab.venue_id,
                    DiningTable.kind == "table",
                )
            )
        ).scalars()
        blocked.update(table_id for table_id in present_tables if table_id is not None)
    return blocked


async def check_available(
    db: AsyncSession,
    table_ids: list[uuid.UUID],
    start: datetime,
    end: datetime,
    *,
    exclude_reservation_id: uuid.UUID | None = None,
    live: bool | None = None,
    ignore_order_occupancy: bool = False,
) -> None:
    if live is None:
        live = start <= datetime.now(UTC) < end
    blocked = await conflicting_resources(
        db,
        table_ids,
        start,
        end,
        exclude_reservation_id=exclude_reservation_id,
        live=live,
        ignore_order_occupancy=ignore_order_occupancy,
    )
    if blocked:
        raise HTTPException(
            409,
            "Ein ausgewählter Tisch oder eine Aktivität ist reserviert oder noch belegt. Andere Plätze oder ein anderes Zeitfenster wählen.",
        )


def check_combination(tables: list[DiningTable], guests: int, *, walk_in: bool = False) -> None:
    if (
        sum(table.seats for table in tables) < guests
        or max(table.min_party for table in tables) > guests
    ):
        raise HTTPException(422, "Die ausgewählten Plätze passen nicht zur Gruppengröße.")
    if walk_in and any(table.kind != "table" for table in tables):
        raise HTTPException(422, "Walk-ins und Warteliste platzieren Gäste an Restauranttischen.")
    if len(tables) == 1:
        return
    if any(table.kind != "table" for table in tables):
        raise HTTPException(422, "Nur Restauranttische lassen sich kombinieren.")
    if len({(table.room_id, table.area) for table in tables}) != 1:
        raise HTTPException(422, "Eine Tischkombination muss im selben Raum und Bereich liegen.")
    remaining = {table.id: table for table in tables[1:]}
    connected = [tables[0]]
    while remaining:
        match = next(
            (
                table
                for table in remaining.values()
                if any(
                    str(table.id) in other.combinable_with or str(other.id) in table.combinable_with
                    for other in connected
                )
            ),
            None,
        )
        if match is None:
            raise HTTPException(
                422, "Diese Tische sind nicht als kombinierbare Nachbarn eingerichtet."
            )
        connected.append(match)
        del remaining[match.id]


async def create_group(
    db: AsyncSession,
    venue_id: uuid.UUID,
    table_ids: list[uuid.UUID],
    guest_name: str,
    guests: int,
    start: datetime,
    end: datetime,
    actor_id: uuid.UUID,
    *,
    source: str = "reservation",
    note: str = "",
    customer_id: uuid.UUID | None = None,
) -> Reservation:
    from app.gastro import service as svc

    now = datetime.now(UTC)
    if not table_ids or len(table_ids) > 8 or len(set(table_ids)) != len(table_ids):
        raise HTTPException(422, "Eine bis acht unterschiedliche Ressourcen auswählen.")
    seated = source in {"walk_in", "waitlist"}
    start = now if seated else start
    if not 0 < (end - start).total_seconds() <= 86400:
        raise HTTPException(
            422, "Das Zeitfenster muss positiv sein und höchstens 24 Stunden dauern."
        )
    tables = await lock_resources(db, venue_id, table_ids)
    check_combination(tables, guests, walk_in=seated)
    await check_available(db, table_ids, start, end, live=True if seated else None)
    row = Reservation(
        venue_id=venue_id,
        table_id=table_ids[0],
        customer_id=customer_id,
        guest_name=guest_name,
        guests=guests,
        starts_at=start,
        ends_at=end,
        status="seated" if seated else "confirmed",
    )
    db.add(row)
    await db.flush()
    db.add(
        ReservationMeta(
            reservation_id=row.id,
            source=source,
            note=note,
            checked_in_at=now if seated else None,
        )
    )
    for position, table_id in enumerate(table_ids):
        db.add(ReservationResource(reservation_id=row.id, table_id=table_id, position=position))
    svc.event(
        db,
        venue_id,
        "reservation.created",
        row.id,
        {"table_ids": [str(value) for value in table_ids], "guests": guests, "source": source},
        actor_id,
    )
    await db.flush()
    return row


async def transition(
    db: AsyncSession,
    venue_id: uuid.UUID,
    reservation_id: uuid.UUID,
    version: int,
    status: str,
    actor_id: uuid.UUID,
) -> Reservation:
    from app.gastro import service as svc

    row = await lock_group(db, venue_id, reservation_id)
    svc.check_version(row.version, version)
    allowed = {"confirmed": {"seated", "cancelled", "no_show"}, "seated": {"completed"}}
    if status not in allowed.get(row.status, set()):
        raise HTTPException(409, "Dieser Wechsel ist für die Reservierung nicht möglich.")
    now = datetime.now(UTC)
    if status == "no_show" and row.starts_at > now:
        raise HTTPException(
            409, "Nicht erschienen kann erst nach Reservierungsbeginn markiert werden."
        )
    if status == "seated":
        if row.ends_at <= now:
            raise HTTPException(409, "Die geplante Zeit ist vorbei. Vor dem Einchecken verlängern.")
        tables = await lock_resources(db, venue_id, await table_ids_for(db, row))
        check_combination(tables, row.guests)
        await check_available(
            db,
            await table_ids_for(db, row),
            now,
            row.ends_at,
            exclude_reservation_id=row.id,
            live=True,
        )
    meta = (
        await db.execute(select(ReservationMeta).where(ReservationMeta.reservation_id == row.id))
    ).scalar_one_or_none()
    if meta is None:
        meta = ReservationMeta(reservation_id=row.id)
        db.add(meta)
    if status == "seated":
        meta.checked_in_at = now
    else:
        meta.closed_at = now
    row.status = status
    row.version += 1
    svc.event(db, venue_id, "reservation.status_changed", row.id, {"status": status}, actor_id)
    await db.flush()
    return row
