from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_serializer, field_validator


def _strip_tz(v: datetime | None) -> datetime | None:
    if isinstance(v, datetime) and v.tzinfo is not None:
        return v.astimezone(UTC).replace(tzinfo=None)
    return v


# ── Time Entry ────────────────────────────────────────────────────────────────


class TimeEntryRead(BaseModel):
    id: uuid.UUID
    worker_id: uuid.UUID
    tenant_id: uuid.UUID
    assignment_id: uuid.UUID | None
    entry_date: date
    clock_in: datetime
    clock_out: datetime | None
    break_minutes: int
    net_minutes: int | None  # computed
    status: str
    location_note: str | None
    project_code: str | None
    cost_center: str | None
    gps_lat: Decimal | None
    gps_lon: Decimal | None
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    rejection_note: str | None
    worker_note: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("clock_in", "clock_out", "approved_at", "created_at", "updated_at")
    def serialize_utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return aware.isoformat()


class TimeEntryCreate(BaseModel):
    """Worker clocks in."""

    entry_date: date | None = None  # defaults to today
    clock_in: datetime | None = None  # defaults to now()
    assignment_id: uuid.UUID | None = None
    location_note: str | None = Field(None, max_length=255)
    project_code: str | None = Field(None, max_length=100)
    cost_center: str | None = Field(None, max_length=100)
    gps_lat: Decimal | None = None
    gps_lon: Decimal | None = None
    worker_note: str | None = None

    _strip_clock_in = field_validator("clock_in", mode="after")(_strip_tz)


class TimeEntryUpdate(BaseModel):
    """Worker clocks out or updates an open entry."""

    clock_out: datetime | None = None
    break_minutes: int | None = Field(None, ge=0, le=1440)
    location_note: str | None = Field(None, max_length=255)
    project_code: str | None = Field(None, max_length=100)
    cost_center: str | None = Field(None, max_length=100)
    worker_note: str | None = None

    _strip_clock_out = field_validator("clock_out", mode="after")(_strip_tz)


class CorrectionCreate(BaseModel):
    new_clock_in: datetime | None = None
    new_clock_out: datetime | None = None
    new_break_minutes: int | None = Field(None, ge=0, le=1440)
    reason: str = Field(..., min_length=5, max_length=500)

    _strip_new_clock_in = field_validator("new_clock_in", mode="after")(_strip_tz)
    _strip_new_clock_out = field_validator("new_clock_out", mode="after")(_strip_tz)


class CorrectionRead(BaseModel):
    id: uuid.UUID
    entry_id: uuid.UUID
    requested_by: uuid.UUID
    old_values: dict[str, Any]
    new_values: dict[str, Any]
    reason: str
    status: str
    resolved_by: uuid.UUID | None
    resolved_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Summary ───────────────────────────────────────────────────────────────────


class TimeEntrySummary(BaseModel):
    period: str  # YYYY-MM
    total_entries: int
    approved_minutes: int
    submitted_minutes: int
    draft_minutes: int
    pending_corrections: int


# ── HR approval ───────────────────────────────────────────────────────────────


class ApprovalAction(BaseModel):
    action: str = Field(..., pattern="^(approve|reject)$")
    note: str | None = None  # required when rejecting


class BulkApprovalRequest(BaseModel):
    entry_ids: list[uuid.UUID] = Field(..., min_length=1)
    action: str = Field(..., pattern="^(approve|reject)$")
    note: str | None = None


class PendingEntryRead(TimeEntryRead):
    """Time entry enriched with worker name for the HR queue."""

    worker_name: str | None
    worker_email: str
