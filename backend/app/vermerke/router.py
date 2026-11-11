"""Vermerke API – palmscout MVP 2.

Mounted at /vermerke (via main.py)
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.security import get_current_user
from app.users.models import User
from app.vermerke.models import Vermerk
from app.vermerke.schemas import VermerkCreate, VermerkRead, VermerkUpdate
from app.vermerke.service import (
    create_vermerk,
    delete_vermerk,
    get_vermerk,
    list_for_application,
    list_for_assignment,
    list_for_candidate,
    update_vermerk,
)

router = APIRouter()


def _require_recruiter(user: User) -> User:
    if user.role != "recruiter":
        raise HTTPException(status_code=403, detail="Nur für Recruiter.")
    return user


@router.post(
    "/",
    response_model=VermerkRead,
    status_code=status.HTTP_201_CREATED,
    summary="Vermerk erstellen",
)
async def create(
    data: VermerkCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Vermerk:
    _require_recruiter(current_user)
    try:
        return await create_vermerk(db, current_user.id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.get(
    "/candidate/{candidate_id}",
    response_model=list[VermerkRead],
    summary="Vermerke zu einem Kandidaten",
)
async def list_candidate(
    candidate_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Vermerk]:
    _require_recruiter(current_user)
    return await list_for_candidate(db, candidate_id, max_visibility="internal")


@router.get(
    "/application/{application_id}",
    response_model=list[VermerkRead],
    summary="Vermerke zu einer Bewerbung",
)
async def list_application(
    application_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Vermerk]:
    _require_recruiter(current_user)
    return await list_for_application(db, application_id, max_visibility="internal")


@router.get(
    "/assignment/{assignment_id}",
    response_model=list[VermerkRead],
    summary="Vermerke zu einem Zeitarbeit-Auftrag",
)
async def list_assignment(
    assignment_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Vermerk]:
    _require_recruiter(current_user)
    return await list_for_assignment(db, assignment_id, max_visibility="internal")


@router.patch(
    "/{vermerk_id}",
    response_model=VermerkRead,
    summary="Vermerk aktualisieren",
)
async def update(
    vermerk_id: uuid.UUID,
    data: VermerkUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Vermerk:
    _require_recruiter(current_user)
    vermerk = await get_vermerk(db, vermerk_id)
    if not vermerk:
        raise HTTPException(status_code=404, detail="Vermerk nicht gefunden.")
    if vermerk.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Nur der Autor kann diesen Vermerk bearbeiten.")
    return await update_vermerk(db, vermerk, data)


@router.delete(
    "/{vermerk_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Vermerk deaktivieren",
)
async def delete(
    vermerk_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    _require_recruiter(current_user)
    vermerk = await get_vermerk(db, vermerk_id)
    if not vermerk:
        raise HTTPException(status_code=404, detail="Vermerk nicht gefunden.")
    if vermerk.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Nur der Autor kann diesen Vermerk löschen.")
    await delete_vermerk(db, vermerk)
