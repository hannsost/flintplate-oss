"""Pydantic schemas for messaging (Sprint 4.5)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class MessageRead(BaseModel):
    id: UUID
    thread_id: UUID
    sender_id: UUID
    sender_name: str | None = None
    sender_role: str = ""
    body: str
    is_internal_note: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ThreadRead(BaseModel):
    id: UUID
    tenant_id: UUID
    worker_id: UUID
    worker_name: str | None = None
    worker_email: str = ""
    assigned_team_id: UUID | None
    assigned_team_name: str | None = None
    claimed_by: UUID | None
    claimed_by_name: str | None = None
    subject: str
    status: str
    last_message_at: datetime | None
    unread_hr: int
    unread_worker: int
    created_at: datetime
    updated_at: datetime
    preview: str = ""  # last message body snippet

    model_config = {"from_attributes": True}


class ThreadWithMessages(ThreadRead):
    messages: list[MessageRead] = []


# ── Worker-facing ─────────────────────────────────────────────────────────────


class NewThreadRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1)
    assigned_team_id: UUID | None = None


class WorkerReplyRequest(BaseModel):
    body: str = Field(..., min_length=1)


# ── HR-facing ─────────────────────────────────────────────────────────────────


class HRReplyRequest(BaseModel):
    body: str = Field(..., min_length=1)
    is_internal_note: bool = False


class AssignTeamRequest(BaseModel):
    team_id: UUID | None
