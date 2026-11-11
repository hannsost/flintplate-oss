from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from app.gastro import service as svc
from app.gastro.models import DiningTable, Floor, Order, Room, UsageSession
from app.gastro.router import DB, Actor, private_response
from app.gastro.schemas import (
    FloorInput,
    FloorRead,
    LineRead,
    OrderRead,
    RoomInput,
    RoomRead,
    TableRead,
    TableUpdate,
    UsageInput,
    UsageRead,
)

router = APIRouter(dependencies=[Depends(private_response)])


async def validate_room(db: DB, venue_id: uuid.UUID, room_id: uuid.UUID | None) -> None:
    if (
        room_id
        and not (
            await db.execute(select(Room.id).where(Room.id == room_id, Room.venue_id == venue_id))
        ).first()
    ):
        raise HTTPException(404, "Raum nicht in diesem Betrieb gefunden.")


@router.get(
    "/venues/{venue_id}/floors",
    response_model=list[FloorRead],
    status_code=200,
    summary="Stockwerke und Außenbereiche",
)
async def floors(venue_id: uuid.UUID, user: Actor, db: DB) -> list[Floor]:
    await svc.venue_access(db, user, venue_id)
    return list(
        (
            await db.execute(
                select(Floor).where(Floor.venue_id == venue_id).order_by(Floor.level, Floor.name)
            )
        ).scalars()
    )


@router.post(
    "/venues/{venue_id}/floors",
    response_model=FloorRead,
    status_code=201,
    summary="Stockwerk oder Außenbereich anlegen",
)
async def create_floor(venue_id: uuid.UUID, data: FloorInput, user: Actor, db: DB) -> Floor:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    if (
        await db.execute(
            select(Floor.id).where(Floor.venue_id == venue_id, Floor.name == data.name)
        )
    ).first():
        raise HTTPException(409, "Dieser Bereich existiert bereits.")
    row = Floor(venue_id=venue_id, **data.model_dump())
    db.add(row)
    await db.flush()
    svc.event(db, venue_id, "floor.created", row.id, data.model_dump(mode="json"), user.id)
    return row


@router.get(
    "/venues/{venue_id}/rooms",
    response_model=list[RoomRead],
    status_code=200,
    summary="Räume je Stockwerk",
)
async def rooms(venue_id: uuid.UUID, user: Actor, db: DB) -> list[Room]:
    await svc.venue_access(db, user, venue_id)
    return list(
        (
            await db.execute(select(Room).where(Room.venue_id == venue_id).order_by(Room.name))
        ).scalars()
    )


@router.post(
    "/venues/{venue_id}/rooms",
    response_model=RoomRead,
    status_code=201,
    summary="Raum oder Aktivitätsbereich anlegen",
)
async def create_room(venue_id: uuid.UUID, data: RoomInput, user: Actor, db: DB) -> Room:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    if not (
        await db.execute(
            select(Floor.id).where(Floor.id == data.floor_id, Floor.venue_id == venue_id)
        )
    ).first():
        raise HTTPException(404, "Stockwerk nicht gefunden.")
    if (
        await db.execute(
            select(Room.id).where(Room.floor_id == data.floor_id, Room.name == data.name)
        )
    ).first():
        raise HTTPException(409, "Dieser Raum existiert bereits.")
    row = Room(venue_id=venue_id, **data.model_dump())
    db.add(row)
    await db.flush()
    svc.event(db, venue_id, "room.created", row.id, data.model_dump(mode="json"), user.id)
    return row


@router.put(
    "/venues/{venue_id}/tables/{table_id}",
    response_model=TableRead,
    status_code=200,
    summary="Position, Raum und Ressourcentarif ändern",
)
async def update_table(
    venue_id: uuid.UUID, table_id: uuid.UUID, data: TableUpdate, user: Actor, db: DB
) -> DiningTable:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    await validate_room(db, venue_id, data.room_id)
    table = await svc.table_for_venue(db, venue_id, table_id, lock=True)
    svc.check_version(table.version, data.version)
    await svc.validate_combinable(db, venue_id, data.combinable_with, table_id)
    if (
        await db.execute(
            select(DiningTable.id).where(
                DiningTable.venue_id == venue_id,
                DiningTable.name == data.name,
                DiningTable.id != table_id,
            )
        )
    ).first():
        raise HTTPException(409, "Dieser Name ist bereits vergeben.")
    if (
        await db.execute(
            select(UsageSession.id).where(
                UsageSession.table_id == table_id, UsageSession.ends_at.is_(None)
            )
        )
    ).first() and data.kind != table.kind:
        raise HTTPException(409, "Eine laufende Nutzung muss zuerst abgeschlossen werden.")
    for field, value in data.model_dump(exclude={"version"}).items():
        setattr(table, field, value)
    table.version += 1
    svc.event(db, venue_id, "table.updated", table.id, data.model_dump(mode="json"), user.id)
    await db.flush()
    return table


@router.get(
    "/venues/{venue_id}/usage",
    response_model=list[UsageRead],
    status_code=200,
    summary="Laufende Aktivitätsnutzungen",
)
async def usages(venue_id: uuid.UUID, user: Actor, db: DB) -> list[UsageSession]:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    return list(
        (
            await db.execute(
                select(UsageSession)
                .where(UsageSession.venue_id == venue_id, UsageSession.ends_at.is_(None))
                .order_by(UsageSession.starts_at)
            )
        ).scalars()
    )


@router.post(
    "/venues/{venue_id}/usage",
    response_model=UsageRead,
    status_code=201,
    summary="Tretboot, Bahn oder andere Aktivität starten",
)
async def start_usage(venue_id: uuid.UUID, data: UsageInput, user: Actor, db: DB) -> UsageSession:
    await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    table = await svc.table_for_venue(db, venue_id, data.table_id, lock=True)
    prior = (
        await db.execute(
            select(UsageSession).where(
                UsageSession.venue_id == venue_id, UsageSession.request_key == data.request_key
            )
        )
    ).scalar_one_or_none()
    if prior:
        if prior.request_hash != svc.digest(data):
            raise HTTPException(409, "Vorgangs-ID bereits anders verwendet.")
        return prior
    if table.kind == "table" or table.hourly_rate_cents <= 0:
        raise HTTPException(422, "Eine Aktivität mit positivem Zeittarif ist erforderlich.")
    if (
        await db.execute(
            select(UsageSession.id).where(
                UsageSession.table_id == table.id, UsageSession.ends_at.is_(None)
            )
        )
    ).first():
        raise HTTPException(409, "Diese Ressource wird bereits genutzt.")
    now = datetime.now(UTC)
    end = now + timedelta(minutes=data.duration_minutes)
    await svc.check_resource_available(db, table.id, now, end)
    row = UsageSession(
        venue_id=venue_id,
        table_id=table.id,
        guest_name=data.guest_name,
        starts_at=now,
        reserved_until=end,
        hourly_rate_cents=table.hourly_rate_cents,
        billing_minutes=table.billing_minutes,
        tax_rate_bps=table.tax_rate_bps,
        request_key=data.request_key,
        request_hash=svc.digest(data),
    )
    db.add(row)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "activity.started",
        row.id,
        {"table_id": str(table.id), "reserved_until": end.isoformat()},
        user.id,
    )
    return row


@router.post(
    "/venues/{venue_id}/usage/{usage_id}/finish",
    response_model=OrderRead,
    status_code=200,
    summary="Aktivität beenden und nach begonnenem Zeitintervall abrechnen",
)
async def finish_usage(venue_id: uuid.UUID, usage_id: uuid.UUID, user: Actor, db: DB) -> Order:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    row = (
        await db.execute(
            select(UsageSession)
            .where(UsageSession.id == usage_id, UsageSession.venue_id == venue_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Nutzung nicht gefunden.")
    if row.order_id:
        return await svc.order_for_venue(db, venue_id, row.order_id)
    table = await svc.table_for_venue(db, venue_id, row.table_id, lock=True)
    now = datetime.now(UTC)
    minutes = max(
        row.billing_minutes,
        math.ceil((now - row.starts_at).total_seconds() / 60 / row.billing_minutes)
        * row.billing_minutes,
    )
    total = int(
        (Decimal(row.hourly_rate_cents) * minutes / 60).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    if total > 100000000:
        raise HTTPException(422, "Nutzungsbetrag überschreitet das Systemlimit. Bitte prüfen.")
    line = LineRead(
        line_id=uuid.uuid4(),
        preparation_status="served",
        kind="activity",
        item_id=table.id,
        sku=f"ACT-{str(table.id)[:8]}",
        name=table.name,
        menu_version=table.version,
        quantity=1,
        price_cents=total,
        tax_rate_bps=row.tax_rate_bps,
        tax_cents=int(
            (Decimal(total) * row.tax_rate_bps / (10000 + row.tax_rate_bps)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        ),
        total_cents=total,
        allergens=[],
        station="service",
        note=f"{minutes} Minuten · {row.billing_minutes}-Minuten-Takt · {row.hourly_rate_cents} ct/Stunde",
    )
    number = (
        await db.execute(select(func.count()).select_from(Order).where(Order.venue_id == venue_id))
    ).scalar_one() + 1001
    order = Order(
        venue_id=venue_id,
        table_id=table.id,
        actor_id=user.id,
        request_key=uuid.uuid4(),
        request_hash=svc.digest(line),
        number=f"FP-{number}",
        status="served",
        fulfillment_status="served",
        lines=[line.model_dump(mode="json")],
        subtotal_cents=total,
        total_cents=total,
        currency=venue.currency,
        guests=1,
        note="Aktivitätsabrechnung",
    )
    db.add(order)
    await db.flush()
    row.ends_at = now
    row.order_id = order.id
    svc.event(
        db,
        venue_id,
        "order.created",
        order.id,
        OrderRead.model_validate(order).model_dump(mode="json"),
        user.id,
    )
    svc.event(
        db,
        venue_id,
        "activity.finished",
        row.id,
        {"order_id": str(order.id), "billed_minutes": minutes},
        user.id,
    )
    return order
