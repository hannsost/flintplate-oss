"""Venue-scoped human assignments on the existing task authority."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro import service as svc
from app.gastro.dependencies import DB, Actor
from app.gastro.models import Membership, Venue
from app.gastro.reporting import ReportingDB
from app.gastro.router import private_response
from app.gastro.task_models import TaskCommand
from app.gastro.task_schemas import (
    Priority,
    Status,
    TaskCommandRead,
    TaskHistoryPage,
    VenueTaskAction,
    VenueTaskCreate,
    VenueTaskPage,
    VenueTaskRead,
)
from app.tasks.models import Task
from app.users.models import User

router = APIRouter(dependencies=[Depends(private_response)])


async def active_assignee(db: AsyncSession, venue: Venue, user_id: uuid.UUID) -> User:
    person = (
        await db.execute(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(
                User.id == user_id,
                User.tenant_id == venue.tenant_id,
                User.is_active.is_(True),
                Membership.venue_id == venue.id,
                Membership.active.is_(True),
                Membership.role.in_(svc.KITCHEN),
            )
        )
    ).scalar_one_or_none()
    if person is None:
        raise HTTPException(422, "Die Aufgabe benötigt eine aktive Person dieses Betriebs.")
    return person


async def task_for(
    db: AsyncSession,
    venue: Venue,
    task_id: uuid.UUID,
    actor_id: uuid.UUID,
    role: str,
    *,
    lock: bool = False,
) -> Task:
    query = (
        select(Task)
        .where(Task.id == task_id, Task.venue_id == venue.id, Task.tenant_id == venue.tenant_id)
        .execution_options(populate_existing=True)
    )
    if role != "manager":
        query = query.where(Task.assigned_to == actor_id)
    if lock:
        query = query.with_for_update()
    task = (await db.execute(query)).scalar_one_or_none()
    if task is None:
        raise HTTPException(404, "Aufgabe nicht gefunden oder nicht zugewiesen.")
    return task


async def read_task(db: AsyncSession, task: Task) -> VenueTaskRead:
    people = {
        person.id: person
        for person in (
            await db.execute(
                select(User).where(
                    User.id.in_(
                        [key for key in (task.assigned_to, task.assigned_by) if key is not None]
                    )
                )
            )
        ).scalars()
    }
    assigned = people.get(task.assigned_to) if task.assigned_to else None
    assigner = people.get(task.assigned_by) if task.assigned_by else None
    if task.venue_id is None or task.assigned_to is None:
        raise HTTPException(404, "Keine menschliche Betriebsaufgabe.")
    return VenueTaskRead(
        id=task.id,
        venue_id=task.venue_id,
        title=task.title,
        description=task.description,
        assigned_to=task.assigned_to,
        assigned_to_name=(
            (assigned.full_name or assigned.email) if assigned else "Unbekannte Person"
        ),
        assigned_by=task.assigned_by,
        assigned_by_name=(assigner.full_name or assigner.email) if assigner else None,
        due_at=task.due_at,
        priority=cast(Priority, task.priority),
        require_completion_note=task.require_completion_note,
        status=cast(Status, task.status),
        version=task.version,
        worker_note=task.worker_note,
        completed_at=task.completed_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


async def previous_command(
    db: AsyncSession,
    venue_id: uuid.UUID,
    key: uuid.UUID,
    fingerprint: str,
    actor_id: uuid.UUID,
    *,
    task_id: uuid.UUID | None = None,
) -> TaskCommand | None:
    row = (
        await db.execute(
            select(TaskCommand).where(
                TaskCommand.venue_id == venue_id, TaskCommand.request_key == key
            )
        )
    ).scalar_one_or_none()
    if row and (
        row.request_hash != fingerprint
        or row.actor_id != actor_id
        or (task_id is not None and row.task_id != task_id)
    ):
        raise HTTPException(409, "Diese Vorgangs-ID wurde bereits anders verwendet.")
    return row


async def record(
    db: AsyncSession,
    venue: Venue,
    task: Task,
    user: User,
    *,
    key: uuid.UUID,
    fingerprint: str,
    kind: str,
    note: str,
    before: VenueTaskRead | None,
) -> VenueTaskRead:
    await db.flush()
    after = await read_task(db, task)
    command = TaskCommand(
        venue_id=venue.id,
        task_id=task.id,
        version=task.version,
        request_key=key,
        request_hash=fingerprint,
        actor_id=user.id,
        actor_name=user.full_name or user.email,
        kind=kind,
        note=note,
        before=before.model_dump(mode="json") if before else None,
        after=after.model_dump(mode="json"),
    )
    db.add(command)
    await db.flush()
    svc.event(
        db,
        venue.id,
        f"task.{kind}",
        task.id,
        {
            "command_id": str(command.id),
            "version": task.version,
            "note": note,
            "before": command.before,
            "after": command.after,
        },
        user.id,
    )
    await db.flush()
    return after


@router.post(
    "/venues/{venue_id}/tasks",
    response_model=VenueTaskRead,
    status_code=201,
    summary="Aufgabe einer aktiven Person des Betriebs zuweisen",
)
async def create_task(
    venue_id: uuid.UUID, data: VenueTaskCreate, user: Actor, db: DB
) -> VenueTaskRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    fingerprint = svc.digest(data)
    previous = await previous_command(db, venue.id, data.request_key, fingerprint, user.id)
    if previous:
        if previous.kind != "create":
            raise HTTPException(409, "Diese Vorgangs-ID gehört zu einer anderen Aufgabenaktion.")
        return VenueTaskRead.model_validate(previous.after)
    await active_assignee(db, venue, data.assigned_to)
    now = datetime.now(UTC)
    task = Task(
        id=uuid.uuid4(),
        tenant_id=venue.tenant_id,
        venue_id=venue.id,
        assigned_to=data.assigned_to,
        assigned_by=user.id,
        title=data.title,
        description=data.description,
        due_at=data.due_at,
        due_date=data.due_at.astimezone(ZoneInfo(venue.timezone)).date() if data.due_at else None,
        priority=data.priority,
        require_completion_note=data.require_completion_note,
        status="open",
        version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    return await record(
        db,
        venue,
        task,
        user,
        key=data.request_key,
        fingerprint=fingerprint,
        kind="create",
        note="Aufgabe zugewiesen",
        before=None,
    )


@router.post(
    "/venues/{venue_id}/tasks/{task_id}/action",
    response_model=VenueTaskRead,
    status_code=201,
    summary="Aufgabe mit geprüftem Versionsstand bearbeiten und protokollieren",
)
async def change_task(
    venue_id: uuid.UUID, task_id: uuid.UUID, data: VenueTaskAction, user: Actor, db: DB
) -> VenueTaskRead:
    venue, role = await svc.venue_access(db, user, venue_id, svc.KITCHEN, lock=True)
    fingerprint = svc.digest(data)
    # A departed/reassigned employee cannot replay another person's current task.
    task = await task_for(db, venue, task_id, user.id, role, lock=True)
    previous = await previous_command(
        db, venue.id, data.request_key, fingerprint, user.id, task_id=task.id
    )
    if previous:
        return VenueTaskRead.model_validate(previous.after)
    svc.check_version(task.version, data.version)
    before = await read_task(db, task)
    if data.action in {"start", "done"}:
        if task.assigned_to != user.id:
            raise HTTPException(
                403, "Übernahme und Erledigung bestätigt die zugewiesene Person selbst."
            )
        await active_assignee(db, venue, user.id)
        expected = {"open"} if data.action == "start" else {"open", "in_progress"}
        if task.status not in expected:
            raise HTTPException(409, "Die Aufgabe hat inzwischen einen anderen Bearbeitungsstand.")
        if data.action == "done" and task.require_completion_note and len(data.note) < 3:
            raise HTTPException(422, "Diese Aufgabe benötigt eine konkrete Abschlussnotiz.")
        task.status = "in_progress" if data.action == "start" else "done"
        task.worker_note = data.note or None
        task.completed_at = datetime.now(UTC) if data.action == "done" else None
    else:
        if role != "manager":
            raise HTTPException(403, "Diese Änderung erfordert die Betriebsleitung.")
        if data.action == "reopen":
            if task.status not in {"done", "cancelled"}:
                raise HTTPException(
                    409, "Nur abgeschlossene Aufgaben können wieder geöffnet werden."
                )
            task.status = "open"
            task.completed_at = None
            task.worker_note = None
        else:
            if task.status in {"done", "cancelled"}:
                raise HTTPException(
                    409, "Die abgeschlossene Aufgabe zuerst ausdrücklich wieder öffnen."
                )
            if data.action == "cancel":
                task.status = "cancelled"
                task.completed_at = None
            elif data.action == "reassign":
                assert data.assigned_to is not None
                await active_assignee(db, venue, data.assigned_to)
                if data.assigned_to == task.assigned_to:
                    raise HTTPException(409, "Die Aufgabe ist dieser Person bereits zugewiesen.")
                task.assigned_to = data.assigned_to
                task.assigned_by = user.id
                task.status = "open"
                task.worker_note = None
                task.completed_at = None
            elif data.action == "edit":
                assert (
                    data.title is not None
                    and data.description is not None
                    and data.priority is not None
                )
                assert data.require_completion_note is not None
                task.require_completion_note = data.require_completion_note
                task.title, task.description, task.priority = (
                    data.title,
                    data.description,
                    data.priority,
                )
                task.due_at = data.due_at
                task.due_date = (
                    data.due_at.astimezone(ZoneInfo(venue.timezone)).date() if data.due_at else None
                )
    task.version += 1
    task.updated_at = datetime.now(UTC)
    return await record(
        db,
        venue,
        task,
        user,
        key=data.request_key,
        fingerprint=fingerprint,
        kind=data.action,
        note=data.note,
        before=before,
    )


@router.get(
    "/venues/{venue_id}/tasks",
    response_model=VenueTaskPage,
    status_code=200,
    summary="Eigene Aufgaben oder die Aufgaben des geleiteten Betriebs seitenweise lesen",
)
async def list_tasks(
    venue_id: uuid.UUID,
    db: ReportingDB,
    user: Actor,
    mine: bool | None = None,
    include_closed: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    before: uuid.UUID | None = None,
) -> VenueTaskPage:
    venue, role = await svc.venue_access(db, user, venue_id, svc.KITCHEN)
    if mine is False and role != "manager":
        raise HTTPException(403, "Die Gesamtübersicht erfordert die Betriebsleitung.")
    query = select(Task).where(Task.venue_id == venue.id, Task.tenant_id == venue.tenant_id)
    own = role != "manager" or mine is True
    if own:
        query = query.where(Task.assigned_to == user.id)
    if not include_closed:
        query = query.where(Task.status.in_(["open", "in_progress"]))
    if before:
        cursor = await task_for(db, venue, before, user.id, "service" if own else role)
        query = query.where(tuple_(Task.created_at, Task.id) < (cursor.created_at, cursor.id))
    rows = list(
        (
            await db.execute(
                query.order_by(Task.created_at.desc(), Task.id.desc()).limit(limit + 1)
            )
        ).scalars()
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return VenueTaskPage(
        items=[await read_task(db, task) for task in rows],
        next_before=rows[-1].id if more else None,
        has_more=more,
    )


@router.get(
    "/venues/{venue_id}/tasks/{task_id}",
    response_model=VenueTaskRead,
    status_code=200,
    summary="Eine zugängliche Betriebsaufgabe lesen",
)
async def get_task(
    venue_id: uuid.UUID, task_id: uuid.UUID, db: ReportingDB, user: Actor
) -> VenueTaskRead:
    venue, role = await svc.venue_access(db, user, venue_id, svc.KITCHEN)
    return await read_task(db, await task_for(db, venue, task_id, user.id, role))


@router.get(
    "/venues/{venue_id}/tasks/{task_id}/history",
    response_model=TaskHistoryPage,
    status_code=200,
    summary="Unveränderlichen Verlauf einer zugänglichen Aufgabe lesen",
)
async def task_history(
    venue_id: uuid.UUID,
    task_id: uuid.UUID,
    db: ReportingDB,
    user: Actor,
    limit: int = Query(default=50, ge=1, le=100),
    before: uuid.UUID | None = None,
) -> TaskHistoryPage:
    venue, role = await svc.venue_access(db, user, venue_id, svc.KITCHEN)
    task = await task_for(db, venue, task_id, user.id, role)
    query = select(TaskCommand).where(
        TaskCommand.task_id == task.id, TaskCommand.venue_id == venue.id
    )
    if before:
        cursor = (
            await db.execute(
                select(TaskCommand).where(
                    TaskCommand.id == before,
                    TaskCommand.venue_id == venue.id,
                    TaskCommand.task_id == task.id,
                )
            )
        ).scalar_one_or_none()
        if cursor is None:
            raise HTTPException(404, "Verlaufsgrenze nicht gefunden.")
        query = query.where(TaskCommand.version < cursor.version)
    rows = list(
        (await db.execute(query.order_by(TaskCommand.version.desc()).limit(limit + 1))).scalars()
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return TaskHistoryPage(
        items=[
            TaskCommandRead(
                id=row.id,
                task_id=row.task_id,
                actor_id=row.actor_id,
                actor_name=row.actor_name,
                kind=row.kind,
                note=row.note,
                before=VenueTaskRead.model_validate(row.before) if row.before else None,
                after=VenueTaskRead.model_validate(row.after),
                created_at=row.created_at,
            )
            for row in rows
        ],
        next_before=rows[-1].id if more else None,
        has_more=more,
    )
