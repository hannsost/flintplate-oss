"""Worker-facing endpoints — /worker/*

Requires role == 'worker'.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.dependencies import DBSession, WorkerUser
from app.worker.models import WorkerSettings
from app.worker.schemas import WorkerMeRead, WorkerModules

router = APIRouter()


@router.get("/me", response_model=WorkerMeRead)
async def worker_me(user: WorkerUser, db: DBSession) -> WorkerMeRead:
    """Worker dashboard bootstrap: own profile + active modules."""
    result = await db.execute(select(WorkerSettings).where(WorkerSettings.user_id == user.id))
    settings = result.scalar_one_or_none()
    if settings is None:
        raise HTTPException(status_code=404, detail="Worker-Profil nicht gefunden.")

    if not settings.is_active:
        raise HTTPException(status_code=403, detail="Worker-Zugang ist deaktiviert.")

    modules_raw: dict[str, Any] = settings.active_modules or {}
    active_modules = WorkerModules(
        **{k: modules_raw.get(k, True) for k in WorkerModules.model_fields}
    )

    return WorkerMeRead(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        active_modules=active_modules,
        employment_type=settings.employment_type,
        tenant_id=settings.tenant_id,
    )


@router.get("/modules", response_model=WorkerModules)
async def worker_modules(user: WorkerUser, db: DBSession) -> WorkerModules:
    """Return the active module flags for this worker (used by frontend gates)."""
    result = await db.execute(select(WorkerSettings).where(WorkerSettings.user_id == user.id))
    settings = result.scalar_one_or_none()
    if settings is None:
        return WorkerModules()  # all enabled as fallback

    modules_raw: dict[str, Any] = settings.active_modules or {}
    return WorkerModules(**{k: modules_raw.get(k, True) for k in WorkerModules.model_fields})
