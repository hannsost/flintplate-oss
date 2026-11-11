from __future__ import annotations

import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro import service as svc
from app.gastro.models import Shift, Venue
from app.gastro.policy import Assessment, assess_interval
from app.gastro.router import DB, Actor, private_response
from app.gastro.schemas import ShiftInput
from app.worker.models import WorkerSettings

router = APIRouter(dependencies=[Depends(private_response)])


async def assess_worker(
    db: AsyncSession, venue: Venue, data: ShiftInput, exclude_id: uuid.UUID | None = None
) -> Assessment:
    settings = (
        await db.execute(
            select(WorkerSettings).where(
                WorkerSettings.user_id == data.worker_id,
                WorkerSettings.tenant_id == venue.tenant_id,
                WorkerSettings.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if settings is None:
        raise HTTPException(404, "Aktiver Mitarbeiterstamm erforderlich.")
    zone = ZoneInfo(venue.timezone)
    start = data.starts_at.astimezone(zone)
    end = data.ends_at.astimezone(zone)
    monday = (start - timedelta(days=start.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    sunday = monday + timedelta(days=7)
    query = select(Shift).where(
        Shift.worker_id == data.worker_id,
        Shift.status != "cancelled",
        Shift.starts_at < sunday + timedelta(days=2),
        Shift.ends_at > monday - timedelta(days=2),
    )
    if exclude_id:
        query = query.where(Shift.id != exclude_id)
    shifts = (await db.execute(query)).scalars().all()
    planned = sum(
        int((row.ends_at - row.starts_at).total_seconds() / 60) - row.break_minutes
        for row in shifts
        if row.starts_at >= monday and row.starts_at < sunday
    )
    return assess_interval(
        start,
        end,
        data.break_minutes,
        settings.date_of_birth,
        [(r.starts_at, r.ends_at) for r in shifts],
        planned,
        settings.max_weekly_hours * 60 if settings.max_weekly_hours else None,
    )


class PlanningRead(BaseModel):
    blockers: list[str]
    warnings: list[str]


@router.post(
    "/venues/{venue_id}/planning/check",
    response_model=PlanningRead,
    status_code=200,
    summary="Arbeitszeit-Vorprüfung mit sichtbaren Grenzen",
)
async def planning_check(
    venue_id: uuid.UUID, data: ShiftInput, user: Actor, db: DB
) -> PlanningRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    assessment = await assess_worker(db, venue, data)
    return PlanningRead(blockers=assessment.blockers, warnings=assessment.warnings)
