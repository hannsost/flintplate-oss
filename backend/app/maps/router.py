"""Map View router – Sprint MVP-2."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.maps.schemas import MapDataResponse
from app.maps.service import get_map_data
from app.security import get_current_user
from app.users.models import User

router = APIRouter()


def _require_recruiter(user: User) -> User:
    if user.role not in {"recruiter", "admin"}:
        raise HTTPException(status_code=403, detail="Nur für Recruiter.")
    if user.tenant_id is None:
        raise HTTPException(status_code=403, detail="Keine Organisation zugewiesen.")
    return user


@router.get("/data", response_model=MapDataResponse)
async def map_data(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MapDataResponse:
    """Return assignments and pool workers with geocoordinates."""
    _require_recruiter(current_user)
    return await get_map_data(db, tenant_id=current_user.tenant_id)
