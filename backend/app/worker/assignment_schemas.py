"""Pydantic schemas for work assignments (Sprint 4.3)."""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, model_validator


class AssignmentBase(BaseModel):
    start_date: date
    end_date: date
    shift_start: time | None = None
    shift_end: time | None = None
    customer_company: str | None = None
    location: str | None = None
    role_description: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def end_after_start(self) -> AssignmentBase:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be >= start_date")
        return self


class AssignmentCreate(AssignmentBase):
    worker_id: UUID
    status: str = "planned"


class AssignmentUpdate(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    shift_start: time | None = None
    shift_end: time | None = None
    customer_company: str | None = None
    location: str | None = None
    role_description: str | None = None
    notes: str | None = None
    status: str | None = None


class AssignmentRead(AssignmentBase):
    id: UUID
    worker_id: UUID
    tenant_id: UUID
    created_by: UUID | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AssignmentWithWorker(AssignmentRead):
    """Complete row used by the HR Einsatzplanung table."""

    worker_name: str | None = None
    worker_email: str
    customer: str | None = None
    shift: str | None = None
    activity: str | None = None


class AssignmentBulkStatusUpdate(BaseModel):
    assignment_ids: list[UUID]
    status: str
