"""Interview schedule schemas – Sprint 1.5."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class InterviewScheduleCreate(BaseModel):
    scheduled_at: AwareDatetime = Field(description="ISO 8601 datetime with timezone")
    meeting_url: str | None = None
    notes: str | None = None


class InterviewScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    proposed_by: uuid.UUID | None
    scheduled_at: datetime
    status: str
    meeting_url: str | None
    notes: str | None
    created_at: datetime


class InterviewScheduleUpdate(BaseModel):
    """Candidate confirms or declines; recruiter can cancel."""

    status: str  # confirmed | declined | cancelled
    notes: str | None = None
