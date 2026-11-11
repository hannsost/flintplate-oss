"""Manager-only creation and inspection of immutable personnel cost revisions."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import JsonValue
from sqlalchemy import select

from app.gastro import service as svc
from app.gastro.labour_models import LabourRateRevision
from app.gastro.labour_schemas import (
    LabourCurrent,
    LabourRevisionInput,
    LabourRevisionRead,
    LabourSummary,
)
from app.gastro.labour_service import current_revisions, labour_summary
from app.gastro.models import Membership, Venue
from app.gastro.reporting import ReportingDB
from app.gastro.router import DB, Actor, private_response
from app.users.models import User

router = APIRouter(dependencies=[Depends(private_response)])


async def staff(db: DB, venue: Venue, worker_id: uuid.UUID) -> User:
    worker = (
        await db.execute(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.venue_id == venue.id,
                User.id == worker_id,
                User.tenant_id == venue.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if worker is None:
        raise HTTPException(404, "Mitarbeitende sind diesem Betrieb nicht zugeordnet.")
    return worker


def request_hash(worker_id: uuid.UUID, data: LabourRevisionInput) -> str:
    return hashlib.sha256(
        json.dumps(
            [str(worker_id), data.model_dump(mode="json")], sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


@router.get(
    "/venues/{venue_id}/labour-rates",
    response_model=list[LabourCurrent],
    status_code=200,
    summary="Aktuelle kalkulatorische Personalkostensätze je Teammitglied",
)
async def rates(venue_id: uuid.UUID, user: Actor, db: DB) -> list[LabourCurrent]:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    workers = (
        await db.execute(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.venue_id == venue.id,
                User.tenant_id == venue.tenant_id,
            )
            .order_by(User.full_name, User.id)
        )
    ).scalars()
    revisions = await current_revisions(db, venue_id)
    return [
        LabourCurrent(
            worker_id=worker.id,
            full_name=worker.full_name or "Teammitglied",
            current=(
                LabourRevisionRead.model_validate(revisions[worker.id])
                if worker.id in revisions
                else None
            ),
        )
        for worker in workers
    ]


@router.get(
    "/venues/{venue_id}/labour-rates/{worker_id}/revisions",
    response_model=list[LabourRevisionRead],
    status_code=200,
    summary="Frühere unveränderliche Satzrevisionen mit Seitenbegrenzung",
)
async def history(
    venue_id: uuid.UUID,
    worker_id: uuid.UUID,
    user: Actor,
    db: DB,
    before_version: int | None = Query(default=None, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
) -> list[LabourRateRevision]:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    await staff(db, venue, worker_id)
    query = select(LabourRateRevision).where(
        LabourRateRevision.venue_id == venue_id,
        LabourRateRevision.worker_id == worker_id,
    )
    if before_version is not None:
        query = query.where(LabourRateRevision.version < before_version)
    return list(
        (await db.execute(query.order_by(LabourRateRevision.version.desc()).limit(limit))).scalars()
    )


@router.get(
    "/venues/{venue_id}/labour-rates/{worker_id}/revisions/{revision_id}",
    response_model=LabourRevisionRead,
    status_code=200,
    summary="Eine konkrete Personalkosten-Quellrevision nachvollziehen",
)
async def read_revision(
    venue_id: uuid.UUID,
    worker_id: uuid.UUID,
    revision_id: uuid.UUID,
    user: Actor,
    db: DB,
) -> LabourRateRevision:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    row = (
        await db.execute(
            select(LabourRateRevision).where(
                LabourRateRevision.venue_id == venue_id,
                LabourRateRevision.worker_id == worker_id,
                LabourRateRevision.id == revision_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Satzrevision nicht in diesem Betrieb gefunden.")
    return row


@router.post(
    "/venues/{venue_id}/labour-rates/{worker_id}",
    response_model=LabourRevisionRead,
    status_code=201,
    summary="Vollständige Gültigkeitsliste als neue belegte Revision speichern",
)
async def revise(
    venue_id: uuid.UUID,
    worker_id: uuid.UUID,
    data: LabourRevisionInput,
    user: Actor,
    db: DB,
) -> LabourRateRevision:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    digest = request_hash(worker_id, data)
    previous_request = (
        await db.execute(
            select(LabourRateRevision).where(
                LabourRateRevision.venue_id == venue_id,
                LabourRateRevision.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if previous_request is not None:
        if previous_request.request_hash != digest:
            raise HTTPException(409, "Diese Vorgangs-ID gehört zu anderen Kostensatzangaben.")
        return previous_request
    await staff(db, venue, worker_id)
    previous = (await current_revisions(db, venue_id, {worker_id})).get(worker_id)
    version = previous.version if previous is not None else 0
    if version != data.version:
        raise HTTPException(409, "Die aktuelle Satzrevision hat sich geändert. Liste neu laden.")
    periods: list[dict[str, JsonValue]] = [
        period.model_dump(mode="json") for period in data.periods
    ]
    row = LabourRateRevision(
        venue_id=venue_id,
        worker_id=worker_id,
        previous_id=previous.id if previous else None,
        version=version + 1,
        currency=venue.currency,
        request_key=data.request_key,
        request_hash=digest,
        actor_id=user.id,
        reason=data.reason,
        source_reference=data.source_reference,
        periods=periods,
    )
    db.add(row)
    await db.flush()
    # The team/device journal must never expose personal wage amounts or sources.
    svc.event(
        db,
        venue_id,
        "labour.rates_revised",
        row.id,
        {"worker_id": str(worker_id), "version": row.version},
        user.id,
    )
    return row


@router.get(
    "/venues/{venue_id}/labour-summary",
    response_model=LabourSummary,
    status_code=200,
    summary="Freigegebene Arbeitszeit nach belegten aktuellen Satzrevisionen bewerten",
)
async def summary(
    venue_id: uuid.UUID,
    db: ReportingDB,
    user: Actor,
    start: datetime,
    end: datetime,
) -> LabourSummary:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    return await labour_summary(db, venue, start, end)
