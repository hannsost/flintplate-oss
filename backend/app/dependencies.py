"""Shared FastAPI dependencies.

Usage in routers:
    from app.dependencies import CurrentUser, DBSession, TenantDB, AdminUser

    @router.get("/me")
    async def me(user: CurrentUser, db: DBSession) -> UserRead: ...

    @router.get("/admin/customers")
    async def list_customers(user: AdminUser, db: DBSession) -> ...: ...
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated, Any

from fastapi import Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import get_redis
from app.database import get_db
from app.users.models import User

# ── Database ──────────────────────────────────────────────────────────────────
DBSession = Annotated[AsyncSession, Depends(get_db)]

# ── Cache ─────────────────────────────────────────────────────────────────────
CacheClient = Annotated[Any, Depends(get_redis)]

# ── Auth ──────────────────────────────────────────────────────────────────────
from app.security import get_current_user  # noqa: E402

CurrentUser = Annotated[Any, Depends(get_current_user)]


# ── Tenant-aware DB session (sets PostgreSQL RLS context) ─────────────────────


async def _get_tenant_db(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[Any, Depends(get_current_user)],
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a DB session with PostgreSQL RLS session variables set.

    SET LOCAL only affects the current transaction, so it is safe with
    connection pooling. Two variables are set:
      - app.current_tenant_id  → used by RLS POLICY to isolate tenant data
      - app.is_admin            → 'true' allows admin bypass of RLS
    """
    tid = str(current_user.tenant_id) if current_user.tenant_id else ""
    is_admin = "true" if current_user.role == "admin" else "false"
    # asyncpg does not support bind parameters for SET LOCAL — embed values directly.
    # Both values come from the validated JWT payload, not raw user input.
    await db.execute(text(f"SET LOCAL app.current_tenant_id = '{tid}'"))
    await db.execute(text(f"SET LOCAL app.is_admin = '{is_admin}'"))
    yield db


TenantDB = Annotated[AsyncSession, Depends(_get_tenant_db)]


# ── Role-gated current user shortcuts ─────────────────────────────────────────


async def _require_admin(user: Annotated[Any, Depends(get_current_user)]) -> Any:
    from app.security import require_admin

    return require_admin(user)


async def _require_platform_admin(user: Annotated[User, Depends(_require_admin)]) -> User:
    if user.tenant_id is not None:
        raise HTTPException(status_code=403, detail="Nur die Plattformadministration hat Zugriff.")
    return user


async def _require_recruiter(user: Annotated[Any, Depends(get_current_user)]) -> Any:
    from app.security import require_recruiter

    return require_recruiter(user)


async def _require_tenant_recruiter(user: Annotated[Any, Depends(_require_recruiter)]) -> Any:
    if user.tenant_id is None:
        raise HTTPException(status_code=403, detail="Keine Organisation zugewiesen.")
    return user


async def _require_worker(user: Annotated[Any, Depends(get_current_user)], db: DBSession) -> Any:
    from sqlalchemy import select

    from app.security import require_worker
    from app.worker.models import WorkerSettings

    require_worker(user)
    settings = await db.scalar(select(WorkerSettings).where(WorkerSettings.user_id == user.id))
    if (
        settings is None
        or not settings.is_active
        or user.tenant_id is None
        or settings.tenant_id != user.tenant_id
    ):
        raise HTTPException(
            status_code=403, detail="Der Zugang zum Mitarbeiterportal ist deaktiviert."
        )
    return user


AdminUser = Annotated[Any, Depends(_require_admin)]
PlatformAdminUser = Annotated[User, Depends(_require_platform_admin)]
RecruiterUser = Annotated[Any, Depends(_require_recruiter)]
TenantRecruiterUser = Annotated[Any, Depends(_require_tenant_recruiter)]
WorkerUser = Annotated[Any, Depends(_require_worker)]
