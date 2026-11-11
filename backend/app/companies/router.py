"""Company endpoints – Sprint 1.2."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.branding import router as branding_router
from app.companies.invitations_router import router as invitations_router
from app.companies.schemas import CompanyCreate, CompanyRead, CompanyUpdate
from app.companies.service import create_company, get_company, update_company
from app.companies.workspace_router import router as workspace_router
from app.database import get_db
from app.integrations.inbox import router as inbox_router
from app.integrations.router import router as integrations_router
from app.journeys.router import router as journeys_router
from app.scheduling.router import router as scheduling_router
from app.security import get_current_user
from app.users.models import User

router = APIRouter()
router.include_router(branding_router)
router.include_router(invitations_router)
router.include_router(workspace_router)
router.include_router(integrations_router)
router.include_router(inbox_router)
router.include_router(scheduling_router)
router.include_router(journeys_router)


def _require_recruiter(user: User) -> User:
    if user.role not in ("recruiter", "admin"):
        raise HTTPException(status_code=403, detail="Nur für Recruiter.")
    return user


@router.post("/", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
async def create(
    data: CompanyCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CompanyRead:
    """Create a company and promote the calling user to recruiter."""
    # Re-read under a row lock so concurrent onboarding cannot create orphan workspaces.
    current_user = (
        await db.scalars(
            select(User)
            .where(User.id == current_user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).one()
    if current_user.company_id:
        raise HTTPException(
            status_code=409, detail="Du bist bereits mit einem Unternehmen verknüpft."
        )
    if current_user.tenant_id is not None:
        raise HTTPException(
            status_code=409, detail="Du bist bereits einer Organisation zugeordnet."
        )
    if current_user.role not in {"candidate", "recruiter", "admin"}:
        raise HTTPException(
            status_code=403, detail="Dieser Kontotyp kann keinen Recruiting-Arbeitsbereich anlegen."
        )
    company = await create_company(db, data, current_user.id)
    return CompanyRead.model_validate(company)


@router.get("/mine", response_model=CompanyRead)
async def get_mine(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CompanyRead:
    _require_recruiter(current_user)
    company = await get_company(db, current_user.company_id)  # type: ignore[arg-type]
    if not company:
        raise HTTPException(status_code=404, detail="Kein Unternehmen gefunden.")
    return CompanyRead.model_validate(company)


@router.patch("/mine", response_model=CompanyRead)
async def update_mine(
    data: CompanyUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CompanyRead:
    _require_recruiter(current_user)
    if current_user.role != "admin":
        raise HTTPException(
            status_code=403, detail="Nur die Firmenadministration darf das Profil ändern."
        )
    company = await get_company(db, current_user.company_id)  # type: ignore[arg-type]
    if not company:
        raise HTTPException(status_code=404, detail="Kein Unternehmen gefunden.")
    updated = await update_company(db, company, data)
    return CompanyRead.model_validate(updated)
