"""Worker self-service profile endpoints – /worker/profile (Sprint 4.11)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.dependencies import DBSession, WorkerUser
from app.users.schemas import Password
from app.worker.models import WorkerSettings

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────


class WorkerProfileRead(BaseModel):
    user_id: str
    email: str
    full_name: str | None
    # WorkerSettings contact fields
    phone: str | None
    address_street: str | None
    address_city: str | None
    address_zip: str | None
    address_country: str | None
    date_of_birth: date | None
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    iban: str | None
    avatar_url: str | None
    # Read-only HR fields
    employment_type: str
    is_active: bool


class WorkerProfileUpdate(BaseModel):
    full_name: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    address_street: str | None = Field(None, max_length=300)
    address_city: str | None = Field(None, max_length=100)
    address_zip: str | None = Field(None, max_length=20)
    address_country: str | None = Field(None, max_length=100)
    date_of_birth: date | None = None
    emergency_contact_name: str | None = Field(None, max_length=200)
    emergency_contact_phone: str | None = Field(None, max_length=50)
    iban: str | None = Field(None, max_length=34)
    avatar_url: str | None = Field(None, max_length=1000)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: Password


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=WorkerProfileRead)
async def get_my_profile(user: WorkerUser, db: DBSession) -> WorkerProfileRead:
    ws_row = await db.execute(select(WorkerSettings).where(WorkerSettings.user_id == user.id))
    ws = ws_row.scalar_one_or_none()
    if ws and not ws.active_modules.get("profile_selfservice", True):
        raise HTTPException(status_code=403, detail="Profil-Modul nicht aktiviert")

    return WorkerProfileRead(
        user_id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        phone=ws.phone if ws else None,
        address_street=ws.address_street if ws else None,
        address_city=ws.address_city if ws else None,
        address_zip=ws.address_zip if ws else None,
        address_country=ws.address_country if ws else "DE",
        date_of_birth=ws.date_of_birth if ws else None,
        emergency_contact_name=ws.emergency_contact_name if ws else None,
        emergency_contact_phone=ws.emergency_contact_phone if ws else None,
        iban=ws.iban if ws else None,
        avatar_url=ws.avatar_url if ws else None,
        employment_type=ws.employment_type if ws else "temp",
        is_active=ws.is_active if ws else True,
    )


@router.patch("", response_model=WorkerProfileRead)
async def update_my_profile(
    body: WorkerProfileUpdate, user: WorkerUser, db: DBSession
) -> WorkerProfileRead:
    from app.users.models import User

    ws_row = await db.execute(select(WorkerSettings).where(WorkerSettings.user_id == user.id))
    ws = ws_row.scalar_one_or_none()
    if ws and not ws.active_modules.get("profile_selfservice", True):
        raise HTTPException(status_code=403, detail="Profil-Modul nicht aktiviert")

    # Update full_name on users table
    if body.full_name is not None:
        u_row = await db.execute(select(User).where(User.id == user.id))
        u = u_row.scalar_one_or_none()
        if u:
            u.full_name = body.full_name

    # Update WorkerSettings contact fields
    if ws:
        profile_fields = [
            "phone",
            "address_street",
            "address_city",
            "address_zip",
            "address_country",
            "date_of_birth",
            "emergency_contact_name",
            "emergency_contact_phone",
            "iban",
            "avatar_url",
        ]
        for field in profile_fields:
            val = getattr(body, field)
            if val is not None:
                setattr(ws, field, val)

    await db.commit()

    # Re-fetch to return updated data
    if ws:
        await db.refresh(ws)
    u_row2 = await db.execute(select(type(user).__class__))  # noqa
    from app.users.models import User as UserModel

    u_row2 = await db.execute(select(UserModel).where(UserModel.id == user.id))
    updated_user = u_row2.scalar_one_or_none() or user

    return WorkerProfileRead(
        user_id=str(updated_user.id),
        email=updated_user.email,
        full_name=updated_user.full_name,
        phone=ws.phone if ws else None,
        address_street=ws.address_street if ws else None,
        address_city=ws.address_city if ws else None,
        address_zip=ws.address_zip if ws else None,
        address_country=ws.address_country if ws else "DE",
        date_of_birth=ws.date_of_birth if ws else None,
        emergency_contact_name=ws.emergency_contact_name if ws else None,
        emergency_contact_phone=ws.emergency_contact_phone if ws else None,
        iban=ws.iban if ws else None,
        avatar_url=ws.avatar_url if ws else None,
        employment_type=ws.employment_type if ws else "temp",
        is_active=ws.is_active if ws else True,
    )


@router.post("/change-password", status_code=204)
async def change_password(body: ChangePasswordRequest, user: WorkerUser, db: DBSession) -> None:
    from passlib.hash import bcrypt

    from app.users.models import User

    u_row = await db.execute(select(User).where(User.id == user.id))
    u = u_row.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")

    if not bcrypt.verify(body.current_password, u.hashed_password):
        raise HTTPException(status_code=400, detail="Aktuelles Passwort ist falsch")

    u.hashed_password = bcrypt.hash(body.new_password)
    u.auth_version += 1
    await db.commit()
