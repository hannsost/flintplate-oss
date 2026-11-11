"""Pydantic schemas for Tasks (Sprint 4.9)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    assigned_to: uuid.UUID
    title: str = Field(..., max_length=300)
    description: str | None = None
    due_date: date | None = None
    priority: str = "medium"


class TaskUpdate(BaseModel):
    title: str | None = Field(None, max_length=300)
    description: str | None = None
    due_date: date | None = None
    priority: str | None = None
    status: str | None = None


class TaskRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    assigned_to: uuid.UUID | None
    assigned_agent_id: uuid.UUID | None
    assigned_by: uuid.UUID | None
    title: str
    description: str | None
    due_date: date | None
    priority: str
    status: str
    completed_at: datetime | None
    worker_note: str | None
    created_at: datetime
    updated_at: datetime
    # Enriched
    assigned_to_name: str | None = None
    assigned_to_email: str = ""
    assigned_by_name: str | None = None

    model_config = {"from_attributes": True}


class WorkerTaskUpdate(BaseModel):
    """Worker can only update status + note."""

    status: str
    worker_note: str | None = None
