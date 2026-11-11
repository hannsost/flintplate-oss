"""Pydantic schemas for absence management (Sprint 4.6)."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

ABSENCE_TYPE_LABELS = {
    "vacation": "Urlaub",
    "sick": "Krankmeldung",
    "unpaid": "Unbezahlte Freistellung",
    "special": "Sonderurlaub",
    "other": "Sonstiges",
}


class AbsenceCreate(BaseModel):
    absence_type: str = Field(..., pattern="^(vacation|sick|unpaid|special|other)$")
    start_date: date
    end_date: date
    worker_note: str | None = None

    @model_validator(mode="after")
    def end_after_start(self) -> AbsenceCreate:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be >= start_date")
        return self


class AbsenceRead(BaseModel):
    id: UUID
    worker_id: UUID
    worker_name: str | None = None
    worker_email: str = ""
    tenant_id: UUID
    absence_type: str
    absence_type_label: str = ""
    start_date: date
    end_date: date
    working_days: int | None
    worker_note: str | None
    status: str
    reviewed_by: UUID | None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None
    reviewer_note: str | None
    certificate_uploaded: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AbsenceReview(BaseModel):
    """HR decision on a pending absence request."""

    action: str = Field(..., pattern="^(approve|reject)$")
    reviewer_note: str | None = None


class AbsenceCancel(BaseModel):
    pass  # worker cancels their own request


class AbsenceSummary(BaseModel):
    """Yearly stats for a worker."""

    year: int
    vacation_days_approved: int
    vacation_days_pending: int
    sick_days_approved: int
    total_approved: int
