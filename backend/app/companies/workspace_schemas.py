"""Explicit response contracts for the shared workspace."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.users.schemas import UserRead


class InvitationCreate(BaseModel):
    email: EmailStr
    role: Literal["recruiter", "admin"] = "recruiter"

    @field_validator("email")
    @classmethod
    def normalize(cls, value: str) -> str:
        return value.strip().lower()


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: str
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None


class InvitationIssued(InvitationRead):
    token: str


class InvitationAccept(BaseModel):
    token: str = Field(min_length=32, max_length=128)


class MemberUpdate(BaseModel):
    role: Literal["recruiter", "admin"]


class MembersRead(BaseModel):
    owner_id: uuid.UUID | None
    members: list[UserRead]
    invitations: list[InvitationRead]


class ActionRead(BaseModel):
    id: str
    kind: str
    title: str
    detail: str
    href: str
    action_label: str
    due_at: datetime | None = None
    urgent: bool = False


class TodayRead(BaseModel):
    generated_at: datetime
    actions: list[ActionRead]


class PersonRead(BaseModel):
    id: uuid.UUID
    full_name: str | None
    email: str
    role: str
    headline: str | None
    location: str | None


class PeopleRead(BaseModel):
    total: int
    people: list[PersonRead]


class PersonApplication(BaseModel):
    id: uuid.UUID
    position: str
    status: str
    updated_at: datetime


class PersonSkill(BaseModel):
    name: str
    source: str | None


class PersonExperience(BaseModel):
    title: str
    company: str
    description: str | None
    source: str | None


class PersonDetail(PersonRead):
    summary: str | None
    skills: list[PersonSkill]
    experience: list[PersonExperience]
    applications: list[PersonApplication]
    actions: list[ActionRead]
