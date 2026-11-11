"""Notification service – create, list, mark-read."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import Notification


async def create_notification(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    type_: str,
    title: str,
    body: str,
    meta: dict[str, Any] | None = None,
) -> Notification:
    n = Notification(user_id=user_id, type=type_, title=title, body=body, meta=meta)
    db.add(n)
    await db.flush()
    return n


async def create_and_push(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    type_: str,
    title: str,
    body: str,
    meta: dict[str, Any] | None = None,
) -> Notification:
    """Create a notification in DB and immediately push it via WebSocket."""
    from app.ws.manager import manager

    n = await create_notification(
        db, user_id=user_id, type_=type_, title=title, body=body, meta=meta
    )
    await manager.send_to_user(
        str(user_id),
        {
            "type": "notification.new",
            "payload": {
                "id": str(n.id),
                "type": n.type,
                "title": n.title,
                "body": n.body,
                "meta": n.meta,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            },
        },
    )
    return n


async def list_notifications(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit: int = 50,
) -> tuple[list[Notification], int]:
    """Return (recent notifications, unread count)."""
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    notifications = list(result.scalars().all())

    unread_result = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id)
        .where(Notification.read_at.is_(None))
    )
    unread = unread_result.scalar_one()
    return notifications, unread


async def mark_all_read(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id)
        .where(Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
        .returning(Notification.id)
    )
    return len(result.fetchall())


async def mark_one_read(db: AsyncSession, notification_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    result = await db.execute(
        update(Notification)
        .where(Notification.id == notification_id)
        .where(Notification.user_id == user_id)
        .where(Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
        .returning(Notification.id)
    )
    return result.fetchone() is not None


async def reminder_already_sent(
    db: AsyncSession,
    user_id: uuid.UUID,
    application_id: uuid.UUID,
    within_days: int = 7,
) -> bool:
    """Check if a reminder for this application was already sent recently."""
    from datetime import timedelta

    cutoff = datetime.now(UTC) - timedelta(days=within_days)
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user_id)
        .where(Notification.type == "reminder")
        .where(Notification.created_at > cutoff)
        .where(Notification.meta["application_id"].astext == str(application_id))
        .limit(1)
    )
    return result.scalar_one_or_none() is not None
