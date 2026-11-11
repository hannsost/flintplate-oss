"""Schemas für Bewerbungs-Tracker – Sprint 0.5."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.applications.models import ApplicationStatus


class ApplicationCreate(BaseModel):
    company: str = Field(max_length=255)
    position: str = Field(max_length=500)
    job_url: str | None = None
    notes: str | None = None
    job_id: uuid.UUID | None = None
    status: ApplicationStatus = ApplicationStatus.RESEARCH
    source_platform: str | None = None  # auto-detected from job_url if not provided


class ApplicationUpdate(BaseModel):
    company: str | None = Field(default=None, max_length=255)
    position: str | None = Field(default=None, max_length=500)
    job_url: str | None = None
    notes: str | None = None
    status: ApplicationStatus | None = None
    note: str | None = None  # optional note logged to history on status change


class ApplicationHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    from_status: ApplicationStatus | None
    to_status: ApplicationStatus
    note: str | None
    changed_at: datetime


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    job_id: uuid.UUID | None
    company: str
    position: str
    job_url: str | None
    notes: str | None
    source_platform: str | None
    status: ApplicationStatus
    applied_at: datetime | None
    created_at: datetime
    updated_at: datetime
    history: list[ApplicationHistoryRead]


class KanbanColumn(BaseModel):
    status: ApplicationStatus
    label: str
    applications: list[ApplicationRead]


class KanbanBoard(BaseModel):
    columns: list[KanbanColumn]
    total: int
