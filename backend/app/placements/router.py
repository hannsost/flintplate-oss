"""Partner placement endpoints – Sprint 1.6.

Mounted at /recruiter/placements  (via main.py)
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.placements.schemas import PlacementCreate, PlacementRead, PlacementStats
from app.placements.service import get_my_placements, get_placement_stats, mark_as_placed
from app.security import get_current_user
from app.users.models import User

router = APIRouter()


def _require_recruiter(user: User) -> User:
    if user.role not in {"recruiter", "admin"}:
        raise HTTPException(status_code=403, detail="Nur für Recruiter.")
    return user


@router.post(
    "/applications/{application_id}/place",
    response_model=PlacementRead,
    status_code=status.HTTP_201_CREATED,
    summary="Kandidaten als platziert markieren",
)
async def place_candidate(
    application_id: uuid.UUID,
    data: PlacementCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlacementRead:
    _require_recruiter(current_user)
    try:
        return await mark_as_placed(db, current_user.id, application_id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


@router.get(
    "/",
    response_model=list[PlacementRead],
    summary="Eigene Placements abrufen",
)
async def list_placements(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PlacementRead]:
    _require_recruiter(current_user)
    return await get_my_placements(db, current_user.id)


@router.get(
    "/stats",
    response_model=PlacementStats,
    summary="Provisions-Statistiken",
)
async def placement_stats(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlacementStats:
    _require_recruiter(current_user)
    return await get_placement_stats(db, current_user.id)
