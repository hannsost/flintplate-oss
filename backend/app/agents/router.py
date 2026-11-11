from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent, AgentEvent, AgentRun
from app.agents.schemas import (
    AgentInput,
    AgentRead,
    AgentUpdate,
    RunRead,
    RunReview,
    TaskAssignment,
)
from app.agents.service import assign, authority, configure, event, read_agent, read_run
from app.companies.branding import own_customer
from app.companies.workspace_access import workspace_admin, workspace_user
from app.database import get_db
from app.tasks.models import Task
from app.users.models import User
from app.workqueue.models import WorkItem

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]
HR = Annotated[User, Depends(workspace_user)]
Admin = Annotated[User, Depends(workspace_admin)]


async def own_agent(
    db: AsyncSession, user: User, agent_id: uuid.UUID, *, lock: bool = False
) -> Agent:
    await own_customer(db, user)
    query = select(Agent).where(Agent.id == agent_id, Agent.tenant_id == user.tenant_id)
    if lock:
        query = query.with_for_update()
    agent = await db.scalar(query.execution_options(populate_existing=True))
    if agent is None:
        raise HTTPException(404, "Agent nicht gefunden.")
    return agent


class MemberOption(BaseModel):
    id: uuid.UUID
    name: str


class AgentOptions(BaseModel):
    can_manage: bool
    current_user_id: uuid.UUID
    members: list[MemberOption]
    external_ai_enabled: bool


@router.get(
    "/options",
    response_model=AgentOptions,
    status_code=200,
    summary="Menschliche Verantwortliche und Prüfer im Firmenbereich",
)
async def options(user: HR, db: DB) -> AgentOptions:
    from app.config import get_settings

    await own_customer(db, user)
    rows = await db.scalars(
        select(User)
        .where(
            User.tenant_id == user.tenant_id,
            User.is_active.is_(True),
            User.role.in_(["admin", "recruiter"]),
        )
        .order_by(User.full_name, User.id)
    )
    return AgentOptions(
        can_manage=user.role == "admin",
        current_user_id=user.id,
        members=[MemberOption(id=row.id, name=row.full_name or row.email) for row in rows],
        external_ai_enabled=get_settings().agents_external_ai_enabled,
    )


@router.get(
    "", response_model=list[AgentRead], status_code=200, summary="Agenten des Firmenbereichs"
)
async def agents(user: HR, db: DB) -> list[AgentRead]:
    await own_customer(db, user)
    rows = await db.scalars(
        select(Agent)
        .where(Agent.tenant_id == user.tenant_id)
        .order_by(Agent.created_at.desc())
        .limit(100)
    )
    return [await read_agent(db, row) for row in rows]


@router.post(
    "",
    response_model=AgentRead,
    status_code=201,
    summary="Agent mit menschlicher Verantwortung konfigurieren",
)
async def create_agent(data: AgentInput, user: Admin, db: DB) -> AgentRead:
    await own_customer(db, user)
    assert user.tenant_id is not None
    agent = Agent(
        tenant_id=user.tenant_id, name=data.name, owner_id=data.owner_id, enabled=data.enabled
    )
    db.add(agent)
    await db.flush()
    await configure(db, agent, data, user)
    return await read_agent(db, agent)


@router.put(
    "/{agent_id}",
    response_model=AgentRead,
    status_code=200,
    summary="Neue Agentenversion speichern oder Agent pausieren",
)
async def update_agent(agent_id: uuid.UUID, data: AgentUpdate, user: Admin, db: DB) -> AgentRead:
    agent = await own_agent(db, user, agent_id, lock=True)
    if agent.version != data.expected_version:
        raise HTTPException(409, "Agent wurde geändert. Bitte neu laden.")
    agent.version += 1
    await configure(db, agent, data, user)
    return await read_agent(db, agent)


@router.post(
    "/{agent_id}/tasks",
    response_model=RunRead,
    status_code=201,
    summary="Aufgabe dauerhaft einem Agenten zuweisen",
)
async def assign_task(agent_id: uuid.UUID, data: TaskAssignment, user: HR, db: DB) -> RunRead:
    agent = await own_agent(db, user, agent_id, lock=True)
    return await read_run(db, await assign(db, agent, user, data))


@router.get(
    "/runs",
    response_model=list[RunRead],
    status_code=200,
    summary="Agentenaufträge und Warteschlangenstatus",
)
async def runs(user: HR, db: DB) -> list[RunRead]:
    await own_customer(db, user)
    rows = await db.scalars(
        select(AgentRun)
        .where(AgentRun.tenant_id == user.tenant_id)
        .order_by(AgentRun.created_at.desc())
        .limit(100)
    )
    return [await read_run(db, run) for run in rows]


async def own_run(
    db: AsyncSession, user: User, run_id: uuid.UUID, *, lock: bool = False
) -> AgentRun:
    await own_customer(db, user)
    run = await db.scalar(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.tenant_id == user.tenant_id)
    )
    if run is None:
        raise HTTPException(404, "Agentenauftrag nicht gefunden.")
    if lock:
        # Same lock order as the executor: queue item, agent, then run/task.
        await db.execute(
            select(WorkItem.id).where(WorkItem.id == run.work_item_id).with_for_update()
        )
        await db.execute(select(Agent.id).where(Agent.id == run.agent_id).with_for_update())
        await db.refresh(run, with_for_update=True)
    return run


@router.get(
    "/runs/{run_id}",
    response_model=RunRead,
    status_code=200,
    summary="Agentenergebnis zur Prüfung laden",
)
async def run_detail(run_id: uuid.UUID, user: HR, db: DB) -> RunRead:
    return await read_run(db, await own_run(db, user, run_id))


class EventRead(BaseModel):
    action: str
    actor_id: uuid.UUID | None
    created_at: datetime


@router.get(
    "/runs/{run_id}/events",
    response_model=list[EventRead],
    status_code=200,
    summary="Verlauf eines Agentenauftrags",
)
async def run_events(run_id: uuid.UUID, user: HR, db: DB) -> list[EventRead]:
    await own_run(db, user, run_id)
    rows = await db.scalars(
        select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.run_version)
    )
    return [
        EventRead(action=row.action, actor_id=row.actor_id, created_at=row.created_at)
        for row in rows
    ]


@router.post(
    "/runs/{run_id}/review",
    response_model=RunRead,
    status_code=200,
    summary="Agentenergebnis durch benannten Menschen prüfen",
)
async def review_run(run_id: uuid.UUID, data: RunReview, user: HR, db: DB) -> RunRead:
    run = await own_run(db, user, run_id, lock=True)
    if run.version != data.expected_version or run.status != "awaiting_review":
        raise HTTPException(409, "Auftrag wurde geändert oder wartet nicht auf Prüfung.")
    if run.reviewer_id != user.id or run.reviewer_auth_version != user.auth_version:
        raise HTTPException(
            403,
            "Nur die weiterhin berechtigte, benannte Prüferin oder der Prüfer darf entscheiden.",
        )
    if data.decision == "approve":
        await authority(db, run, lock=True)
    task = await db.get(Task, run.task_id, with_for_update=True)
    if task is None:
        raise HTTPException(409, "Aufgabe fehlt.")
    now = datetime.now(UTC)
    run.status = "approved" if data.decision == "approve" else "rejected"
    run.version += 1
    run.review_note, run.reviewed_at = data.note, now
    task.status = "done" if data.decision == "approve" else "cancelled"
    task.completed_at = now if data.decision == "approve" else None
    task.updated_at = now
    event(db, run, user.id, run.status)
    return await read_run(db, run)


class CancelRequest(BaseModel):
    expected_version: int = Field(ge=1)


@router.post(
    "/runs/{run_id}/cancel",
    response_model=RunRead,
    status_code=200,
    summary="Agentenauftrag abbrechen und weitere Verarbeitung sperren",
)
async def cancel_run(run_id: uuid.UUID, data: CancelRequest, user: HR, db: DB) -> RunRead:
    run = await own_run(db, user, run_id, lock=True)
    if user.id not in {run.delegated_by, run.reviewer_id} and user.role != "admin":
        raise HTTPException(
            403, "Nur Auftraggeber, Prüfer oder Firmenadministration dürfen abbrechen."
        )
    if run.version != data.expected_version or run.status in {"approved", "rejected", "cancelled"}:
        raise HTTPException(409, "Auftrag wurde geändert oder bereits abgeschlossen.")
    item = await db.get(WorkItem, run.work_item_id, populate_existing=True)
    task = await db.get(Task, run.task_id, with_for_update=True)
    assert item is not None and task is not None
    item.status, item.claim_token, item.lease_until = "cancelled", None, None
    task.status = "cancelled"
    run.status = "cancelled"
    run.version += 1
    event(db, run, user.id, "cancelled")
    return await read_run(db, run)
