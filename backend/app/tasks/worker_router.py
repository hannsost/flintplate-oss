"""Worker-facing task endpoints – /worker/tasks (Sprint 4.9)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.dependencies import DBSession, WorkerUser
from app.tasks.models import TASK_STATUSES, Task
from app.tasks.schemas import TaskRead, WorkerTaskUpdate

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
    return r


@router.get("", response_model=list[TaskRead])
async def list_my_tasks(
    user: WorkerUser,
    db: DBSession,
    status: str | None = Query(None),
) -> list[TaskRead]:
    from app.worker.models import WorkerSettings

    ws_row = await db.execute(select(WorkerSettings).where(WorkerSettings.user_id == user.id))
    ws = ws_row.scalar_one_or_none()
    if ws and not ws.active_modules.get("tasks", True):
        raise HTTPException(status_code=403, detail="Aufgaben-Modul nicht aktiviert")

    stmt = select(Task).where(
        Task.assigned_to == user.id, Task.tenant_id == user.tenant_id, Task.venue_id.is_(None)
    )
    if status:
        stmt = stmt.where(Task.status == status)
    stmt = stmt.order_by(Task.due_date.asc().nullslast(), Task.created_at.desc())
    rows = await db.execute(stmt)
    tasks = list(rows.scalars().all())
    return [await _enrich(t, db) for t in tasks]


@router.patch("/{task_id}", response_model=TaskRead)
async def update_my_task(
    task_id: str, body: WorkerTaskUpdate, user: WorkerUser, db: DBSession
) -> TaskRead:
    row = await db.execute(
        select(Task).where(
            Task.id == task_id, Task.assigned_to == user.id, Task.tenant_id == user.tenant_id
        )
    )
    task = row.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")
    if task.venue_id is not None:
        raise HTTPException(
            409,
            "Betriebsaufgaben bitte in FlintPlate mit Rollenprüfung und Versionsbeleg bearbeiten.",
        )
    if body.status not in TASK_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {TASK_STATUSES}")

    now = datetime.now()
    task.status = body.status
    if body.worker_note is not None:
        task.worker_note = body.worker_note
    if body.status == "done" and not task.completed_at:
        task.completed_at = now
    elif body.status != "done":
        task.completed_at = None
    task.updated_at = now
    await db.commit()
    await db.refresh(task)
    return await _enrich(task, db)
