from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

# ── Module config ─────────────────────────────────────────────────────────────


class WorkerModules(BaseModel):
    timetracking: bool = True
    schedule: bool = True
    messages: bool = True
    documents: bool = True
    absences: bool = True
    equipment: bool = True
    tasks: bool = True
    payroll: bool = True
    tickets: bool = True
    profile_selfservice: bool = True


# ── WorkerSettings ────────────────────────────────────────────────────────────


class WorkerSettingsRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    is_active: bool
    employment_type: str
    max_weekly_hours: int | None
    hourly_rate: Decimal | None
    active_modules: dict[str, Any]
    internal_note: str | None
    assigned_manager_id: uuid.UUID | None
    assigned_team_id: uuid.UUID | None = None
    activated_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Profile self-service fields
    phone: str | None = None
    address_street: str | None = None
    address_city: str | None = None
    address_zip: str | None = None
    address_country: str | None = None
    date_of_birth: date | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    iban: str | None = None
    avatar_url: str | None = None

    model_config = {"from_attributes": True}


class WorkerSettingsUpdate(BaseModel):
    is_active: bool | None = None
    employment_type: str | None = Field(None, pattern="^(fulltime|parttime|minijob|temp)$")
    max_weekly_hours: int | None = Field(None, ge=1, le=60)
    hourly_rate: Decimal | None = None
    active_modules: WorkerModules | None = None
    internal_note: str | None = None
    assigned_manager_id: uuid.UUID | None = None
    assigned_team_id: uuid.UUID | None = None


# ── HR management ─────────────────────────────────────────────────────────────


class WorkerActivateRequest(BaseModel):
    """Promote a single candidate to worker role."""

    user_id: uuid.UUID
    employment_type: str = Field("temp", pattern="^(fulltime|parttime|minijob|temp)$")
    max_weekly_hours: int | None = Field(None, ge=1, le=60)
    hourly_rate: Decimal | None = None
    assigned_manager_id: uuid.UUID | None = None
    internal_note: str | None = None


class WorkerBulkRequest(BaseModel):
    """Bulk action over a list of worker user_ids."""

    user_ids: list[uuid.UUID] = Field(..., min_length=1)
    action: str = Field(..., pattern="^(activate|deactivate|assign_manager)$")
    # Only required for assign_manager
    assigned_manager_id: uuid.UUID | None = None


class ManagerRead(BaseModel):
    id: uuid.UUID
    full_name: str | None
    email: str

    model_config = {"from_attributes": True}


class TeamSummaryRead(BaseModel):
    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class WorkerListRead(BaseModel):
    """Combined user + settings row for the HR management table."""

    id: uuid.UUID  # user id
    full_name: str | None
    email: str
    is_active_user: bool
    settings: WorkerSettingsRead | None
    # denormalised for quick table display
    employment_type: str | None
    modules_enabled: int  # count of enabled modules
    manager: ManagerRead | None
    team: TeamSummaryRead | None = None

    model_config = {"from_attributes": True}


# ── Worker-facing ─────────────────────────────────────────────────────────────


class WorkerMeRead(BaseModel):
    id: uuid.UUID
    full_name: str | None
    email: str
    active_modules: WorkerModules
    employment_type: str
    tenant_id: uuid.UUID

    model_config = {"from_attributes": True}
