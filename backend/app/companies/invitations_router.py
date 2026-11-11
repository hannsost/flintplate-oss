"""Email-bound, expiring invitations and protected company administration."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import TokenResponse
from app.companies.models import Company
from app.companies.workspace_access import workspace_admin
from app.companies.workspace_models import WorkspaceInvitation
from app.companies.workspace_schemas import (
    InvitationAccept,
    InvitationCreate,
    InvitationIssued,
    InvitationRead,
    MembersRead,
    MemberUpdate,
)
from app.database import get_db
from app.security import create_access_token, create_refresh_token, get_current_user
from app.users.models import User
from app.users.schemas import UserRead

router = APIRouter(prefix="/workspace")
Admin = Annotated[User, Depends(workspace_admin)]
DB = Annotated[AsyncSession, Depends(get_db)]


async def locked_company(db: AsyncSession, user: User) -> Company:
    company = (
        await db.execute(select(Company).where(Company.id == user.company_id).with_for_update())
    ).scalar_one_or_none()
    if company is None:
        raise HTTPException(409, "Bitte zuerst ein Unternehmensprofil mit Firmeninhaber anlegen.")
    return company


@router.get("/members", response_model=MembersRead, status_code=200, summary="Firmenzugänge")
async def members(user: Admin, db: DB) -> MembersRead:
    company = await db.get(Company, user.company_id) if user.company_id else None
    users = (
        await db.execute(select(User).where(User.tenant_id == user.tenant_id).order_by(User.email))
    ).scalars()
    invitations = (
        await db.execute(
            select(WorkspaceInvitation)
            .where(WorkspaceInvitation.tenant_id == user.tenant_id)
            .order_by(WorkspaceInvitation.created_at.desc())
            .limit(100)
        )
    ).scalars()
    return MembersRead(
        owner_id=company.created_by if company else None,
        members=[UserRead.model_validate(member) for member in users],
        invitations=[InvitationRead.model_validate(invitation) for invitation in invitations],
    )


@router.post(
    "/invitations",
    response_model=InvitationIssued,
    status_code=201,
    summary="Einladungslink erstellen",
)
async def invite(
    data: InvitationCreate, user: Admin, db: DB, response: Response
) -> InvitationIssued:
    company = await locked_company(db, user)
    if data.role == "admin" and company.created_by != user.id:
        raise HTTPException(403, "Nur der Firmeninhaber darf neue Verwaltungszugänge einladen.")
    existing = (
        await db.execute(select(User).where(func.lower(User.email) == data.email))
    ).scalar_one_or_none()
    if existing and (
        existing.tenant_id is not None
        or existing.company_id is not None
        or existing.role not in {"candidate", "recruiter"}
    ):
        raise HTTPException(
            409,
            "Diese Adresse kann nicht eingeladen werden. Bestehende Firmenzuordnungen bleiben erhalten.",
        )
    now = datetime.now(UTC)
    pending = (
        await db.execute(
            select(WorkspaceInvitation).where(
                WorkspaceInvitation.tenant_id == user.tenant_id,
                WorkspaceInvitation.email == data.email,
                WorkspaceInvitation.accepted_at.is_(None),
                WorkspaceInvitation.revoked_at.is_(None),
            )
        )
    ).scalars()
    for previous in pending:
        previous.revoked_at = now
    token = secrets.token_urlsafe(32)
    invitation = WorkspaceInvitation(
        tenant_id=user.tenant_id,
        company_id=company.id,
        invited_by=user.id,
        email=data.email,
        role=data.role,
        token_digest=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=now + timedelta(days=7),
    )
    db.add(invitation)
    await db.flush()
    response.headers["Cache-Control"] = "no-store"
    return InvitationIssued(**InvitationRead.model_validate(invitation).model_dump(), token=token)


@router.delete(
    "/invitations/{invitation_id}",
    response_model=None,
    status_code=204,
    summary="Einladung widerrufen",
)
async def revoke(invitation_id: uuid.UUID, user: Admin, db: DB) -> None:
    invitation = (
        await db.execute(
            select(WorkspaceInvitation)
            .where(
                WorkspaceInvitation.id == invitation_id,
                WorkspaceInvitation.tenant_id == user.tenant_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if invitation is None:
        raise HTTPException(404, "Einladung nicht gefunden.")
    if invitation.accepted_at is not None:
        raise HTTPException(409, "Die Einladung wurde bereits angenommen.")
    invitation.revoked_at = datetime.now(UTC)
    await db.flush()


@router.post(
    "/invitations/accept",
    response_model=TokenResponse,
    status_code=200,
    summary="Einladung mit dem eingeladenen Konto annehmen",
)
async def accept(
    data: InvitationAccept,
    user: Annotated[User, Depends(get_current_user)],
    db: DB,
    response: Response,
) -> TokenResponse:
    user = (
        await db.execute(
            select(User)
            .where(User.id == user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    invitation = (
        await db.execute(
            select(WorkspaceInvitation)
            .where(
                WorkspaceInvitation.token_digest == hashlib.sha256(data.token.encode()).hexdigest()
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if (
        invitation is None
        or invitation.revoked_at
        or invitation.accepted_at
        or invitation.expires_at <= now
    ):
        raise HTTPException(410, "Diese Einladung ist ungültig, abgelaufen oder bereits verwendet.")
    if user.email.lower() != invitation.email:
        raise HTTPException(403, "Bitte mit der eingeladenen E-Mail-Adresse anmelden.")
    if (
        user.tenant_id is not None
        or user.company_id is not None
        or user.role not in {"candidate", "recruiter"}
    ):
        raise HTTPException(409, "Das Konto ist bereits zugeordnet oder kann nicht beitreten.")
    user.tenant_id = invitation.tenant_id
    user.company_id = invitation.company_id
    user.role = invitation.role
    user.auth_version += 1
    invitation.accepted_at = now
    await db.flush()
    claims = {
        "sub": user.email,
        "role": user.role,
        "tenant_id": str(user.tenant_id),
        "ver": user.auth_version,
    }
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(
        access_token=create_access_token(claims), refresh_token=create_refresh_token(claims)
    )


@router.patch(
    "/members/{member_id}", response_model=UserRead, status_code=200, summary="Firmenrolle ändern"
)
async def change_role(member_id: uuid.UUID, data: MemberUpdate, user: Admin, db: DB) -> UserRead:
    company = await locked_company(db, user)
    if company.created_by != user.id:
        raise HTTPException(403, "Nur der Firmeninhaber darf Verwaltungsrechte ändern.")
    if company.created_by == member_id:
        raise HTTPException(409, "Der Firmeninhaber behält seinen Verwaltungszugang.")
    member = (
        await db.execute(
            select(User)
            .where(User.id == member_id, User.tenant_id == user.tenant_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(404, "Mitglied nicht gefunden.")
    if member.role not in {"recruiter", "admin"} or not member.is_active:
        raise HTTPException(409, "Dieser Zugang wird über die Mitarbeitendenverwaltung verwaltet.")
    if member.role != data.role:
        member.role = data.role
        member.auth_version += 1
    await db.flush()
    return UserRead.model_validate(member)
