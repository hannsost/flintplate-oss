"""Manager-configured stations and replayable mutations within a venue."""

from __future__ import annotations

import hashlib
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, text

from app.gastro import service as svc
from app.gastro.router import DB, Actor, private_response
from app.gastro.station_models import OperatingStation, StationCommand
from app.gastro.station_schemas import StationCreate, StationRead, StationUpdate
from app.gastro.station_service import PREPARATION_KINDS, require_unused

router = APIRouter(dependencies=[Depends(private_response)])


def digest(kind: str, target: uuid.UUID | None, data: BaseModel) -> str:
    return hashlib.sha256(
        json.dumps(
            [kind, str(target), data.model_dump(mode="json")], sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


async def prior(
    db: DB, venue_id: uuid.UUID, key: uuid.UUID, fingerprint: str
) -> StationRead | None:
    # Every station mutation locks Venue first, then its request key and row.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,782))"),
        {"key": f"{venue_id}:{key}"},
    )
    row = (
        await db.execute(
            select(StationCommand).where(
                StationCommand.venue_id == venue_id, StationCommand.request_key == key
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.request_hash != fingerprint:
        raise HTTPException(409, "Diese Vorgangs-ID wurde mit anderen Stationsangaben verwendet.")
    return StationRead.model_validate(row.result)


async def record(
    db: DB, row: OperatingStation, kind: str, key: uuid.UUID, fingerprint: str, actor_id: uuid.UUID
) -> StationRead:
    await db.flush()
    result = StationRead.model_validate(row)
    db.add(
        StationCommand(
            venue_id=row.venue_id,
            request_key=key,
            request_hash=fingerprint,
            kind=kind,
            actor_id=actor_id,
            result=result.model_dump(mode="json"),
        )
    )
    svc.event(db, row.venue_id, f"station.{kind}", row.id, result.model_dump(mode="json"), actor_id)
    await db.flush()
    return result


async def unique_name(
    db: DB, venue_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None
) -> None:
    query = select(OperatingStation.id).where(
        OperatingStation.venue_id == venue_id,
        func.lower(OperatingStation.name) == func.lower(name),
    )
    if exclude is not None:
        query = query.where(OperatingStation.id != exclude)
    if (await db.execute(query)).first():
        raise HTTPException(409, "Eine Station dieses Namens existiert bereits.")


@router.get(
    "/venues/{venue_id}/stations",
    response_model=list[StationRead],
    status_code=200,
    summary="Konfigurierte Betriebsstationen anzeigen",
)
async def list_stations(
    venue_id: uuid.UUID,
    user: Actor,
    db: DB,
    include_inactive: bool = False,
    preparation_only: bool = False,
) -> list[OperatingStation]:
    await svc.venue_access(db, user, venue_id)
    query = select(OperatingStation).where(OperatingStation.venue_id == venue_id)
    if not include_inactive:
        query = query.where(OperatingStation.active.is_(True))
    if preparation_only:
        query = query.where(OperatingStation.kind.in_(PREPARATION_KINDS))
    return list(
        (
            await db.execute(
                query.order_by(
                    OperatingStation.sort_order, OperatingStation.name, OperatingStation.id
                )
            )
        ).scalars()
    )


@router.post(
    "/venues/{venue_id}/stations",
    response_model=StationRead,
    status_code=201,
    summary="Eine echte Betriebsstation anlegen",
)
async def create_station(
    venue_id: uuid.UUID, data: StationCreate, user: Actor, db: DB
) -> StationRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    fingerprint = digest("created", None, data)
    existing = await prior(db, venue_id, data.request_key, fingerprint)
    if existing is not None:
        return existing
    await unique_name(db, venue_id, data.name)
    count = await db.scalar(
        select(func.count())
        .select_from(OperatingStation)
        .where(OperatingStation.venue_id == venue_id, OperatingStation.active.is_(True))
    )
    if count is not None and count >= 64:
        raise HTTPException(409, "Höchstens 64 Stationen können gleichzeitig aktiv sein.")
    row_id = uuid.uuid4()
    row = OperatingStation(
        id=row_id,
        venue_id=venue_id,
        code="s_" + row_id.hex,
        name=data.name,
        kind=data.kind,
        sort_order=data.sort_order,
    )
    db.add(row)
    return await record(db, row, "created", data.request_key, fingerprint, user.id)


@router.put(
    "/venues/{venue_id}/stations/{station_id}",
    response_model=StationRead,
    status_code=200,
    summary="Stationsname und Aktivität mit Versionsprüfung ändern",
)
async def update_station(
    venue_id: uuid.UUID, station_id: uuid.UUID, data: StationUpdate, user: Actor, db: DB
) -> StationRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    fingerprint = digest("updated", station_id, data)
    existing = await prior(db, venue_id, data.request_key, fingerprint)
    if existing is not None:
        return existing
    row = (
        await db.execute(
            select(OperatingStation)
            .where(OperatingStation.id == station_id, OperatingStation.venue_id == venue_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Station nicht in diesem Betrieb gefunden.")
    svc.check_version(row.version, data.version)
    await unique_name(db, venue_id, data.name, row.id)
    if row.active and not data.active:
        await require_unused(db, row)
    if not row.active and data.active:
        count = await db.scalar(
            select(func.count())
            .select_from(OperatingStation)
            .where(OperatingStation.venue_id == venue_id, OperatingStation.active.is_(True))
        )
        if count is not None and count >= 64:
            raise HTTPException(409, "Höchstens 64 Stationen können gleichzeitig aktiv sein.")
    row.name, row.active, row.sort_order = data.name, data.active, data.sort_order
    row.version += 1
    return await record(db, row, "updated", data.request_key, fingerprint, user.id)
