"""Bewerbungs-Tracker endpoints – Sprint 0.5."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.models import Application, ApplicationStatus
from app.applications.schemas import (
    ApplicationCreate,
    ApplicationRead,
    ApplicationUpdate,
    KanbanBoard,
    KanbanColumn,
)
from app.applications.service import (
    create_application,
    delete_application,
    get_applications,
    update_application,
)
from app.database import get_db
from app.security import get_current_user
from app.users.models import User

router = APIRouter()

KANBAN_LABELS = {
    ApplicationStatus.RESEARCH: "Recherche",
    ApplicationStatus.APPLIED: "Beworben",
    ApplicationStatus.SCREENING: "Screening",
    ApplicationStatus.INTERVIEW: "Interview",
    ApplicationStatus.OFFER: "Angebot",
    ApplicationStatus.REJECTED: "Abgelehnt",
    ApplicationStatus.WITHDRAWN: "Zurückgezogen",
}


@router.get("/kanban", response_model=KanbanBoard, summary="Kanban-Board aller Bewerbungen")
async def get_kanban(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KanbanBoard:
    apps = await get_applications(db, current_user.id)
    by_status: dict[ApplicationStatus, list[Any]] = {s: [] for s in ApplicationStatus}
    for app in apps:
        by_status[app.status].append(app)

    columns = [
        KanbanColumn(
            status=status,
            label=KANBAN_LABELS[status],
            applications=by_status[status],
        )
        for status in ApplicationStatus
    ]
    return KanbanBoard(columns=columns, total=len(apps))


@router.get("", response_model=list[ApplicationRead], summary="Alle Bewerbungen")
async def list_applications(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Application]:
    return await get_applications(db, current_user.id)


@router.post("", response_model=ApplicationRead, status_code=status.HTTP_201_CREATED)
async def create(
    data: ApplicationCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Application:
    return await create_application(db, current_user.id, data)


@router.patch("/{application_id}", response_model=ApplicationRead)
async def update(
    application_id: uuid.UUID,
    data: ApplicationUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Application:
    apps = await get_applications(db, current_user.id)
    app = next((a for a in apps if a.id == application_id), None)
    if not app:
        raise HTTPException(status_code=404, detail="Bewerbung nicht gefunden.")
    return await update_application(db, app, data)


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    application_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    apps = await get_applications(db, current_user.id)
    app = next((a for a in apps if a.id == application_id), None)
    if not app:
        raise HTTPException(status_code=404, detail="Bewerbung nicht gefunden.")
    await delete_application(db, app)
