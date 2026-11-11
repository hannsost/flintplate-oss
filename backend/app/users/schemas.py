"""Pydantic v2 schemas for users and DSGVO consent."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, field_validator


def _password_bytes(value: str) -> str:
    if len(value.encode("utf-8")) > 72:
        raise ValueError("Passwort darf höchstens 72 UTF-8-Bytes enthalten.")
    return value


Password = Annotated[str, Field(min_length=8, max_length=72), AfterValidator(_password_bytes)]


class UserCreate(BaseModel):
    email: EmailStr
    password: Password
    full_name: str | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None
    is_active: bool
    is_verified: bool
    role: str
    tenant_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    created_at: datetime


class UserUpdate(BaseModel):
    full_name: str | None = None
    password: Password | None = None


class ConsentUpdate(BaseModel):
    ai_opt_in: bool
    terms_accepted: bool


class ConsentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    ai_opt_in: bool
    ai_opt_in_at: datetime | None
    terms_accepted: bool
    terms_accepted_at: datetime | None
    created_at: datetime


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: str
    status: str
    trial_ends_at: datetime | None
