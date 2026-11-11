from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.absences.models import Absence
from app.companies.branding import own_customer
from app.companies.workspace_access import workspace_user
from app.database import get_db
from app.mobility.models import MobilityPlan
from app.mobility.planner import Person, PlanInput, PlanResult, optimise
from app.profiles.models import CandidateProfile, Skill
from app.users.models import User
from app.worker.assignment_models import WorkerAssignment
from app.worker.models import WorkerSettings

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]
HR = Annotated[User, Depends(workspace_user)]


class WorkerRead(BaseModel):
    id: UUID
    name: str
    skills: list[str]


class PlanRead(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    inputs: PlanInput
    result: PlanResult
    model_config = {"from_attributes": True}


async def people_in_workspace(db: AsyncSession, user: User) -> list[WorkerRead]:
    members = (
        await db.scalars(
            select(User)
            .join(WorkerSettings, WorkerSettings.user_id == User.id)
            .where(
                User.tenant_id == user.tenant_id,
                User.role == "worker",
                User.is_active.is_(True),
                WorkerSettings.tenant_id == user.tenant_id,
                WorkerSettings.is_active.is_(True),
            )
            .order_by(User.full_name, User.id)
            .limit(500)
        )
    ).all()
    if not members:
        return []
    skills = (
        await db.execute(
            select(CandidateProfile.user_id, Skill.name)
            .join(Skill, Skill.profile_id == CandidateProfile.id)
            .where(CandidateProfile.user_id.in_([m.id for m in members]))
        )
    ).all()
    return [
        WorkerRead(
            id=m.id,
            name=m.full_name or "Mitarbeitende",
            skills=sorted(s for uid, s in skills if uid == m.id),
        )
        for m in members
    ]


@router.get(
    "/workers",
    response_model=list[WorkerRead],
    status_code=200,
    summary="Eigene aktive Mitarbeitende für die Fahrplanung",
)
async def workers(user: HR, db: DB) -> list[WorkerRead]:
    await own_customer(db, user)
    return await people_in_workspace(db, user)


@router.post(
    "/plans",
    response_model=PlanRead,
    status_code=201,
    summary="Besetzung und Direktfahrten gemeinsam planen",
)
async def create_plan(data: PlanInput, user: HR, db: DB) -> PlanRead:
    await own_customer(db, user)
    members = {m.id: m for m in await people_in_workspace(db, user)}
    ids = [w.worker_id for w in data.workers]
    if any(uid not in members for uid in ids):
        raise HTTPException(404, "Mitarbeitende nicht im aktiven Personalbestand gefunden.")
    # Conservative date overlap: existing multi-day assignments block the date,
    # even if their exact shift times are missing. No medical reason is returned.
    first = (
        (
            data.shift_start
            - timedelta(
                minutes=max(t.outbound_minutes for t in data.trips) + data.arrival_buffer_minutes
            )
        )
        .astimezone(ZoneInfo(data.time_zone))
        .date()
    )
    last = (
        (data.shift_end + timedelta(minutes=max(t.return_minutes for t in data.trips)))
        .astimezone(ZoneInfo(data.time_zone))
        .date()
    )
    assigned = (
        await db.scalars(
            select(WorkerAssignment.worker_id).where(
                WorkerAssignment.tenant_id == user.tenant_id,
                WorkerAssignment.worker_id.in_(ids),
                WorkerAssignment.status.in_(["planned", "confirmed", "active"]),
                WorkerAssignment.start_date <= last,
                WorkerAssignment.end_date >= first,
            )
        )
    ).all()
    absent = (
        await db.scalars(
            select(Absence.worker_id).where(
                Absence.tenant_id == user.tenant_id,
                Absence.worker_id.in_(ids),
                Absence.status.in_(["pending", "approved"]),
                Absence.start_date <= last,
                Absence.end_date >= first,
            )
        )
    ).all()
    blocked = set(assigned) | set(absent)
    people = {
        uid: Person(
            members[uid].name, {s.casefold().strip() for s in members[uid].skills}, uid in blocked
        )
        for uid in ids
    }
    result = optimise(data, people)
    plan = MobilityPlan(
        tenant_id=user.tenant_id,
        created_by=user.id,
        title=data.title,
        inputs=data.model_dump(mode="json"),
        result=result.model_dump(mode="json"),
    )
    db.add(plan)
    await db.flush()
    return PlanRead.model_validate(plan)


@router.get(
    "/plans",
    response_model=list[PlanRead],
    status_code=200,
    summary="Gespeicherte Planungsvorschläge",
)
async def plans(user: HR, db: DB) -> list[PlanRead]:
    await own_customer(db, user)
    rows = await db.scalars(
        select(MobilityPlan)
        .where(MobilityPlan.tenant_id == user.tenant_id)
        .order_by(MobilityPlan.created_at.desc())
        .limit(30)
    )
    return [PlanRead.model_validate(p) for p in rows]


@router.get(
    "/plans/{plan_id}",
    response_model=PlanRead,
    status_code=200,
    summary="Planungsvorschlag mit Eingaben und Ausschlussgründen",
)
async def detail(plan_id: UUID, user: HR, db: DB) -> PlanRead:
    await own_customer(db, user)
    plan = await db.scalar(
        select(MobilityPlan).where(
            MobilityPlan.id == plan_id, MobilityPlan.tenant_id == user.tenant_id
        )
    )
    if plan is None:
        raise HTTPException(404, "Planung nicht gefunden.")
    return PlanRead.model_validate(plan)
