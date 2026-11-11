"""Notifications REST endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.notifications.schemas import NotificationListResponse, NotificationRead
from app.notifications.service import list_notifications, mark_all_read, mark_one_read
from app.security import get_current_user
from app.users.models import User

router = APIRouter()


@router.get("/", response_model=NotificationListResponse)
async def get_notifications(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> NotificationListResponse:
    notifications, unread = await list_notifications(db, current_user.id)
    return NotificationListResponse(
        notifications=[NotificationRead.model_validate(n) for n in notifications],
        unread_count=unread,
    )


@router.post("/read-all", status_code=status.HTTP_200_OK)
async def read_all(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    count = await mark_all_read(db, current_user.id)
    return {"marked_read": count}


@router.patch("/{notification_id}/read", status_code=status.HTTP_200_OK)
async def read_one(
    notification_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    ok = await mark_one_read(db, notification_id, current_user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Notification nicht gefunden.")
    return {"ok": True}
