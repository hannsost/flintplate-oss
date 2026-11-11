"""User endpoints: profile, DSGVO consent, module access."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.security import get_current_user
from app.users.models import PrivacyConsent, User
from app.users.schemas import ConsentRead, ConsentUpdate, UserRead, UserUpdate, WorkspaceRead

router = APIRouter()


@router.get(
    "/me",
    response_model=UserRead,
    summary="Eigenes Profil abrufen",
)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user


@router.patch(
    "/me",
    response_model=UserRead,
    summary="Eigenen Account aktualisieren (Name, Passwort)",
)
async def update_me(
    body: UserUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if body.full_name is not None:
        current_user.full_name = body.full_name
    if body.password is not None:
        from app.security import hash_password

        current_user.hashed_password = hash_password(body.password)
        current_user.auth_version += 1
    await db.flush()
    await db.commit()
    return current_user


@router.get(
    "/consent",
    response_model=ConsentRead | None,
    summary="Aktuelle DSGVO-Einwilligung abrufen",
)
async def get_consent(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PrivacyConsent | None:
    result = await db.execute(
        select(PrivacyConsent).where(PrivacyConsent.user_id == current_user.id)
    )
    return result.scalar_one_or_none()


@router.patch(
    "/consent",
    response_model=ConsentRead,
    summary="DSGVO-Einwilligung aktualisieren (KI-Opt-in)",
)
async def update_consent(
    body: ConsentUpdate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PrivacyConsent:
    result = await db.execute(
        select(PrivacyConsent).where(PrivacyConsent.user_id == current_user.id)
    )
    consent: PrivacyConsent | None = result.scalar_one_or_none()

    if consent is None:
        consent = PrivacyConsent(user_id=current_user.id)
        db.add(consent)

    now = datetime.now(UTC).replace(tzinfo=None)  # store as naive UTC

    # KI-Opt-in mit Timestamp (DSGVO: Widerruf löscht Timestamp)
    consent.ai_opt_in = body.ai_opt_in
    consent.ai_opt_in_at = now if body.ai_opt_in else None

    # Nutzungsbedingungen
    consent.terms_accepted = body.terms_accepted
    consent.terms_accepted_at = now if body.terms_accepted else None

    # Audit-Trail (anonymisierter Kontext)
    consent.ip_address = request.client.host if request.client else None
    consent.user_agent = request.headers.get("user-agent", "")[:500]

    await db.flush()
    return consent


@router.get(
    "/my-modules",
    response_model=list[str],
    summary="Aktive Module für aktuellen Tenant",
)
async def get_my_modules(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[str]:
    """Return module keys whose organization and module access are still valid."""
    from app.admin.entitlements import enabled_modules
    from app.admin.models import MODULES

    if current_user.tenant_id is None:
        # Personal candidate accounts and platform administration have no tenant.
        if current_user.role in {"candidate", "admin"}:
            return [m["key"] for m in MODULES]
        return []
    return await enabled_modules(db, current_user.tenant_id)


class UserSummary(BaseModel):
    id: str
    full_name: str | None
    email: str
    role: str

    model_config = {"from_attributes": True}


@router.get(
    "/list", response_model=list[UserSummary], summary="List tenant users (recruiter/admin)"
)
async def list_tenant_users(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[UserSummary]:
    """Returns all recruiter/admin users in the same tenant. Used for team member selection."""
    if not current_user.tenant_id:
        return []
    result = await db.execute(
        select(User)
        .where(
            User.tenant_id == current_user.tenant_id,
            User.role.in_(["recruiter", "admin"]),
            User.is_active == True,  # noqa: E712
        )
        .order_by(User.full_name)
    )
    return [
        UserSummary(id=str(u.id), full_name=u.full_name, email=u.email, role=u.role)
        for u in result.scalars()
    ]


@router.get("/workspace", response_model=WorkspaceRead | None)
async def get_workspace(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceRead | None:
    """Expose only the current user's organization, without billing or private notes."""
    from app.admin.models import Customer

    if current_user.tenant_id is None:
        return None
    workspace = await db.get(Customer, current_user.tenant_id)
    return WorkspaceRead.model_validate(workspace) if workspace else None
