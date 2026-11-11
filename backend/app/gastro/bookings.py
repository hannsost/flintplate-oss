"""Grouped reservations, real walk-ins and a waitlist with atomic placement."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, JsonValue
from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro import booking_service as booking
from app.gastro import service as svc
from app.gastro.booking_models import ReservationCommand, WaitlistEntry
from app.gastro.booking_schemas import (
    BoardRead,
    ExtendInput,
    GroupInput,
    GroupRead,
    GroupState,
    WaitlistInput,
    WaitlistRead,
    WaitlistSeat,
    WaitlistState,
)
from app.gastro.models import Reservation
from app.gastro.router import DB, Actor, private_response

router = APIRouter(dependencies=[Depends(private_response)])


def fingerprint(kind: str, data: BaseModel, target: uuid.UUID | None) -> str:
    return hashlib.sha256(
        json.dumps([kind, str(target), data.model_dump(mode="json")], sort_keys=True).encode()
    ).hexdigest()


async def prior_command(
    db: AsyncSession, venue_id: uuid.UUID, key: uuid.UUID, digest: str
) -> dict[str, JsonValue] | None:
    # The key is serialized before any physical rows. A retry using a different
    # table set cannot slip through before the unique command is committed.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,740))"),
        {"key": f"{venue_id}:{key}"},
    )
    prior = (
        await db.execute(
            select(ReservationCommand).where(
                ReservationCommand.venue_id == venue_id, ReservationCommand.request_key == key
            )
        )
    ).scalar_one_or_none()
    if prior is None:
        return None
    if prior.request_hash != digest:
        raise HTTPException(409, "Diese Vorgangs-ID wurde bereits mit anderen Angaben verwendet.")
    return prior.result


async def record_command(
    db: AsyncSession,
    venue_id: uuid.UUID,
    key: uuid.UUID,
    digest: str,
    kind: str,
    actor_id: uuid.UUID,
    result: BaseModel,
) -> None:
    db.add(
        ReservationCommand(
            venue_id=venue_id,
            request_key=key,
            request_hash=digest,
            kind=kind,
            result=result.model_dump(mode="json"),
            actor_id=actor_id,
        )
    )
    await db.flush()


@router.get(
    "/venues/{venue_id}/reservations/board",
    response_model=BoardRead,
    status_code=200,
    summary="Reservierungen und tatsächliche Belegung samt Warteliste anzeigen",
)
async def board(
    venue_id: uuid.UUID,
    user: Actor,
    db: DB,
    start: datetime | None = None,
    end: datetime | None = None,
) -> BoardRead:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    lower = start or datetime.now(UTC) - timedelta(days=1)
    upper = end or lower + timedelta(days=32)
    if (
        lower.tzinfo is None
        or upper.tzinfo is None
        or not timedelta(0) < upper - lower <= timedelta(days=93)
    ):
        raise HTTPException(422, "Zeitraum mit Zeitzone und höchstens 93 Tagen erforderlich.")
    rows = list(
        (
            await db.execute(
                select(Reservation)
                .where(
                    Reservation.venue_id == venue_id,
                    or_(
                        and_(Reservation.starts_at < upper, Reservation.ends_at > lower),
                        Reservation.status == "seated",
                    ),
                )
                .order_by(Reservation.starts_at, Reservation.id)
                .limit(10001)
            )
        ).scalars()
    )
    waiting = list(
        (
            await db.execute(
                select(WaitlistEntry)
                .where(WaitlistEntry.venue_id == venue_id, WaitlistEntry.status == "waiting")
                .order_by(WaitlistEntry.created_at, WaitlistEntry.id)
                .limit(10001)
            )
        ).scalars()
    )
    if len(rows) > 10000 or len(waiting) > 10000:
        raise HTTPException(
            409, "Zu viele aktive Einträge; Zeitraum begrenzen oder alte Vorgänge abschließen."
        )
    return BoardRead(
        reservations=await booking.group_reads(db, rows),
        waitlist=[WaitlistRead.model_validate(row) for row in waiting],
    )


@router.post(
    "/venues/{venue_id}/reservation-groups",
    response_model=GroupRead,
    status_code=201,
    summary="Eine Tischgruppe reservieren oder einen Walk-in direkt platzieren",
)
async def create(venue_id: uuid.UUID, data: GroupInput, user: Actor, db: DB) -> GroupRead:
    await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    digest = fingerprint("create", data, None)
    prior = await prior_command(db, venue_id, data.request_key, digest)
    if prior is not None:
        return GroupRead.model_validate(prior)
    row = await booking.create_group(
        db,
        venue_id,
        data.table_ids,
        data.guest_name,
        data.guests,
        data.starts_at,
        data.ends_at,
        user.id,
        source=data.source,
        note=data.note,
    )
    result = await booking.group_read(db, row)
    await record_command(db, venue_id, data.request_key, digest, "create", user.id, result)
    return result


@router.post(
    "/venues/{venue_id}/reservation-groups/{reservation_id}/state",
    response_model=GroupRead,
    status_code=200,
    summary="Gesamte Gruppe einchecken, abschließen oder als nicht erschienen markieren",
)
async def state(
    venue_id: uuid.UUID, reservation_id: uuid.UUID, data: GroupState, user: Actor, db: DB
) -> GroupRead:
    await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    digest = fingerprint("state", data, reservation_id)
    prior = await prior_command(db, venue_id, data.request_key, digest)
    if prior is not None:
        return GroupRead.model_validate(prior)
    row = await booking.transition(db, venue_id, reservation_id, data.version, data.status, user.id)
    result = await booking.group_read(db, row)
    await record_command(db, venue_id, data.request_key, digest, "state", user.id, result)
    return result


@router.post(
    "/venues/{venue_id}/reservation-groups/{reservation_id}/extend",
    response_model=GroupRead,
    status_code=200,
    summary="Reservierung nach erneuter Belegungsprüfung für alle Tische verlängern",
)
async def extend(
    venue_id: uuid.UUID, reservation_id: uuid.UUID, data: ExtendInput, user: Actor, db: DB
) -> GroupRead:
    await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    digest = fingerprint("extend", data, reservation_id)
    prior = await prior_command(db, venue_id, data.request_key, digest)
    if prior is not None:
        return GroupRead.model_validate(prior)
    row = await booking.lock_group(db, venue_id, reservation_id)
    svc.check_version(row.version, data.version)
    if row.status not in {"confirmed", "seated"}:
        raise HTTPException(409, "Nur offene Reservierungen lassen sich verlängern.")
    if (
        data.ends_at <= row.ends_at
        or data.ends_at <= datetime.now(UTC)
        or data.ends_at - row.starts_at > timedelta(days=1)
    ):
        raise HTTPException(422, "Neues Ende muss später liegen, insgesamt höchstens 24 Stunden.")
    await booking.check_available(
        db,
        await booking.table_ids_for(db, row),
        row.starts_at,
        data.ends_at,
        exclude_reservation_id=row.id,
        live=row.status == "seated",
        # An existing group's own open bill is expected during extension.
        ignore_order_occupancy=True,
    )
    previous_end = row.ends_at
    row.ends_at = data.ends_at
    row.version += 1
    svc.event(
        db,
        venue_id,
        "reservation.extended",
        row.id,
        {
            "previous_end": previous_end.isoformat(),
            "ends_at": data.ends_at.isoformat(),
            "reason": data.reason,
        },
        user.id,
    )
    await db.flush()
    result = await booking.group_read(db, row)
    await record_command(db, venue_id, data.request_key, digest, "extend", user.id, result)
    return result


async def waitlist_for(
    db: AsyncSession, venue_id: uuid.UUID, entry_id: uuid.UUID, version: int
) -> WaitlistEntry:
    row = (
        await db.execute(
            select(WaitlistEntry)
            .where(WaitlistEntry.id == entry_id, WaitlistEntry.venue_id == venue_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Wartelisteneintrag nicht gefunden.")
    svc.check_version(row.version, version)
    if row.status != "waiting":
        raise HTTPException(409, "Diese Gruppe wartet nicht mehr auf einen Platz.")
    return row


@router.post(
    "/venues/{venue_id}/waitlist",
    response_model=WaitlistRead,
    status_code=201,
    summary="Wartende Gäste ohne erfundenen Tisch in die Warteliste aufnehmen",
)
async def add_waitlist(
    venue_id: uuid.UUID, data: WaitlistInput, user: Actor, db: DB
) -> WaitlistRead:
    await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    digest = fingerprint("waitlist", data, None)
    prior = await prior_command(db, venue_id, data.request_key, digest)
    if prior is not None:
        return WaitlistRead.model_validate(prior)
    row = WaitlistEntry(
        venue_id=venue_id,
        guest_name=data.guest_name,
        guests=data.guests,
        note=data.note,
        actor_id=user.id,
    )
    db.add(row)
    await db.flush()
    svc.event(db, venue_id, "waitlist.created", row.id, {"guests": data.guests}, user.id)
    result = WaitlistRead.model_validate(row)
    await record_command(db, venue_id, data.request_key, digest, "waitlist", user.id, result)
    return result


@router.post(
    "/venues/{venue_id}/waitlist/{entry_id}/seat",
    response_model=GroupRead,
    status_code=201,
    summary="Wartende Gruppe genau einmal an freie Tische setzen",
)
async def seat_waitlist(
    venue_id: uuid.UUID, entry_id: uuid.UUID, data: WaitlistSeat, user: Actor, db: DB
) -> GroupRead:
    await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    digest = fingerprint("waitlist.seat", data, entry_id)
    prior = await prior_command(db, venue_id, data.request_key, digest)
    if prior is not None:
        return GroupRead.model_validate(prior)
    waiting = await waitlist_for(db, venue_id, entry_id, data.version)
    row = await booking.create_group(
        db,
        venue_id,
        data.table_ids,
        waiting.guest_name,
        waiting.guests,
        datetime.now(UTC),
        data.ends_at,
        user.id,
        source="waitlist",
        note=waiting.note,
    )
    waiting.status = "seated"
    waiting.reservation_id = row.id
    waiting.closed_at = datetime.now(UTC)
    waiting.version += 1
    svc.event(db, venue_id, "waitlist.seated", waiting.id, {"reservation_id": str(row.id)}, user.id)
    await db.flush()
    result = await booking.group_read(db, row)
    await record_command(db, venue_id, data.request_key, digest, "waitlist.seat", user.id, result)
    return result


@router.post(
    "/venues/{venue_id}/waitlist/{entry_id}/state",
    response_model=WaitlistRead,
    status_code=200,
    summary="Nicht mehr wartende Gäste nachvollziehbar aus der Warteliste nehmen",
)
async def cancel_waitlist(
    venue_id: uuid.UUID, entry_id: uuid.UUID, data: WaitlistState, user: Actor, db: DB
) -> WaitlistRead:
    await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    digest = fingerprint("waitlist.cancel", data, entry_id)
    prior = await prior_command(db, venue_id, data.request_key, digest)
    if prior is not None:
        return WaitlistRead.model_validate(prior)
    row = await waitlist_for(db, venue_id, entry_id, data.version)
    row.status = "cancelled"
    row.version += 1
    row.closed_at = datetime.now(UTC)
    svc.event(db, venue_id, "waitlist.cancelled", row.id, {}, user.id)
    await db.flush()
    result = WaitlistRead.model_validate(row)
    await record_command(db, venue_id, data.request_key, digest, "waitlist.cancel", user.id, result)
    return result
