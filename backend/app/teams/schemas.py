"""Pydantic schemas for team management (Sprint 4.4)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ── Team Member ───────────────────────────────────────────────────────────────


class TeamMemberRead(BaseModel):
    id: UUID
    team_id: UUID
    user_id: UUID
    role: str
    joined_at: datetime
    # Enriched from users table
    full_name: str | None = None
    email: str = ""

    model_config = {"from_attributes": True}


class TeamMemberAdd(BaseModel):
    user_id: UUID
    role: str = "member"  # lead | member | viewer


class TeamMemberUpdate(BaseModel):
    role: str


# ── Team ──────────────────────────────────────────────────────────────────────


class TeamCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    parent_team_id: UUID | None = None


class TeamUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    parent_team_id: UUID | None = None
    is_active: bool | None = None


class TeamRead(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    parent_team_id: UUID | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    member_count: int = 0

    model_config = {"from_attributes": True}


class TeamWithMembers(TeamRead):
    members: list[TeamMemberRead] = []


# ── Recruiter's team membership summary ──────────────────────────────────────


class MyTeamRead(BaseModel):
    """Returned by GET /teams/mine – teams the current user belongs to."""

    id: UUID
    name: str
    role: str  # this user's role in the team
    member_count: int
