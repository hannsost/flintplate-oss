"""HR task management endpoints – /zeitarbeit/tasks (Sprint 4.9)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.dependencies import DBSession, TenantRecruiterUser
from app.tasks.models import TASK_PRIORITIES, TASK_STATUSES, Task
from app.tasks.schemas import TaskCreate, TaskRead, TaskUpdate
from app.worker.access import require_member

router = APIRouter()


async def _enrich(task: Task, db: DBSession) -> TaskRead:
    from app.users.models import User

    user_ids = {str(task.assigned_to)} if task.assigned_to else set()
    if task.assigned_by:
        user_ids.add(str(task.assigned_by))
    rows = await db.execute(select(User).where(User.id.in_(user_ids)))
    users = {str(u.id): u for u in rows.scalars()}

    assignee = users.get(str(task.assigned_to))
    assigner = users.get(str(task.assigned_by)) if task.assigned_by else None

    r = TaskRead.model_validate(task)
    r.assigned_to_name = assignee.full_name if assignee else None
    r.assigned_to_email = assignee.email if assignee else ""
    r.assigned_by_name = (assigner.full_name or assigner.email) if assigner else None
    if task.assigned_agent_id:
        from app.agents.models import Agent

        agent = await db.get(Agent, task.assigned_agent_id)
        r.assigned_to_name = f"Agent: {agent.name}" if agent else "Agent"
    return r


@router.get("", response_model=list[TaskRead])
async def list_tasks(
    user: TenantRecruiterUser,
    db: DBSession,
    worker_id: str | None = Query(None),
    status: str | None = Query(None),
    priority: str | None = Query(None),
) -> list[TaskRead]:
    stmt = select(Task).where(Task.tenant_id == user.tenant_id, Task.venue_id.is_(None))
    if worker_id:
        stmt = stmt.where(Task.assigned_to == worker_id)
    if status:
        if status not in TASK_STATUSES:
            raise HTTPException(status_code=422, detail=f"status must be one of {TASK_STATUSES}")
        stmt = stmt.where(Task.status == status)
    if priority:
        if priority not in TASK_PRIORITIES:
            raise HTTPException(
                status_code=422, detail=f"priority must be one of {TASK_PRIORITIES}"
            )
        stmt = stmt.where(Task.priority == priority)
    stmt = stmt.order_by(Task.due_date.asc().nullslast(), Task.created_at.desc())
    rows = await db.execute(stmt)
    tasks = list(rows.scalars().all())
    return [await _enrich(t, db) for t in tasks]


@router.post("", response_model=TaskRead, status_code=201)
async def create_task(body: TaskCreate, user: TenantRecruiterUser, db: DBSession) -> TaskRead:
    await require_member(db, user.tenant_id, body.assigned_to)
    if body.priority not in TASK_PRIORITIES:
        raise HTTPException(status_code=422, detail=f"priority must be one of {TASK_PRIORITIES}")
    task = Task(
        tenant_id=user.tenant_id,
        assigned_to=body.assigned_to,
        assigned_by=user.id,
        title=body.title,
        description=body.description,
        due_date=body.due_date,
        priority=body.priority,
        status="open",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return await _enrich(task, db)


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(task_id: str, user: TenantRecruiterUser, db: DBSession) -> TaskRead:
    row = await db.execute(select(Task).where(Task.id == task_id, Task.tenant_id == user.tenant_id))
    task = row.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")
    if task.venue_id is not None:
        raise HTTPException(
            409,
            "Betriebsaufgaben bitte in FlintPlate mit Rollenprüfung und Versionsbeleg bearbeiten.",
        )
    return await _enrich(task, db)


@router.patch("/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: str, body: TaskUpdate, user: TenantRecruiterUser, db: DBSession
) -> TaskRead:
    row = await db.execute(select(Task).where(Task.id == task_id, Task.tenant_id == user.tenant_id))
    task = row.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")
    if task.venue_id is not None:
        raise HTTPException(
            409,
            "Betriebsaufgaben bitte in FlintPlate mit Rollenprüfung und Versionsbeleg bearbeiten.",
        )
    if task.assigned_agent_id is not None:
        raise HTTPException(409, "Agentenaufgaben bitte über die Ergebnisprüfung verwalten.")
    if body.status is not None and body.status not in TASK_STATUSES:
        raise HTTPException(422, "Ungültiger Aufgabenstatus.")
    if body.priority is not None and body.priority not in TASK_PRIORITIES:
        raise HTTPException(422, "Ungültige Priorität.")
    now = datetime.now(UTC)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(task, field, value)
    if body.status == "done" and not task.completed_at:
        task.completed_at = now
    elif body.status and body.status != "done":
        task.completed_at = None
    task.updated_at = now
    await db.commit()
    await db.refresh(task)
    return await _enrich(task, db)


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: str, user: TenantRecruiterUser, db: DBSession) -> None:
    row = await db.execute(select(Task).where(Task.id == task_id, Task.tenant_id == user.tenant_id))
    task = row.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")
    if task.venue_id is not None:
        raise HTTPException(
            409,
            "Betriebsaufgaben bitte in FlintPlate mit Rollenprüfung und Versionsbeleg bearbeiten.",
        )
    if task.assigned_agent_id is not None:
        raise HTTPException(409, "Agentenaufträge bitte abbrechen; der Verlauf bleibt erhalten.")
    await db.delete(task)
    await db.commit()
