"""Validate people referenced by an HR operation before writing any data."""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import User


async def require_member(
    db: AsyncSession,
    tenant_id: uuid.UUID | None,
    user_id: uuid.UUID,
    roles: tuple[str, ...] = ("worker",),
) -> User:
    if tenant_id is None:
        raise HTTPException(status_code=403, detail="Keine Organisation zugewiesen.")
    member = await db.scalar(
        select(User).where(
            User.id == user_id,
            User.tenant_id == tenant_id,
            User.role.in_(roles),
            User.is_active.is_(True),
        )
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Person nicht in dieser Organisation gefunden.")
    return member
