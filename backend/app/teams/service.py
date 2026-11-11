"""Resolve only active teams belonging to the current organization."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.teams.models import Team


async def require_team(db: AsyncSession, tenant_id: UUID | None, team_id: UUID) -> Team:
    team = await db.scalar(
        select(Team).where(
            Team.id == team_id, Team.tenant_id == tenant_id, Team.is_active.is_(True)
        )
    )
    if team is None:
        raise HTTPException(status_code=404, detail="Team nicht gefunden.")
    return team
