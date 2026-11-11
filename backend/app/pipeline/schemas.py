"""Pipeline Builder Pydantic schemas – palmscout MVP 2."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PipelineStageCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    position: int = Field(..., ge=0)
    color: str | None = None
    is_terminal: bool = False
    on_enter_actions: list[dict[str, Any]] | None = None
    sla_hours: int | None = Field(None, ge=1)
    sla_escalate_to: str | None = None
    requires_approval: bool = False
    approver_role: str | None = None


class PipelineStageUpdate(BaseModel):
    name: str | None = None
    position: int | None = None
    color: str | None = None
    is_terminal: bool | None = None
    on_enter_actions: list[dict[str, Any]] | None = None
    sla_hours: int | None = None
    sla_escalate_to: str | None = None
    requires_approval: bool | None = None
    approver_role: str | None = None


class PipelineStageRead(BaseModel):
    id: uuid.UUID
    template_id: uuid.UUID
    name: str
    position: int
    color: str | None
    is_terminal: bool
    on_enter_actions: list[dict[str, Any]] | None
    sla_hours: int | None
    sla_escalate_to: str | None
    requires_approval: bool
    approver_role: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PipelineTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    stages: list[PipelineStageCreate] = []


class PipelineTemplateUpdate(BaseModel):
    name: str | None = None
    is_default: bool | None = None


class PipelineTemplateRead(BaseModel):
    id: uuid.UUID
    recruiter_id: uuid.UUID | None
    company_id: uuid.UUID | None
    name: str
    is_default: bool
    stages: list[PipelineStageRead]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StageTransitionRequest(BaseModel):
    application_id: uuid.UUID
    to_stage_id: uuid.UUID
    note: str | None = None


class StageTransitionResponse(BaseModel):
    application_id: uuid.UUID
    stage: PipelineStageRead


class ApplicationStageHistoryRead(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    from_stage_id: uuid.UUID | None
    to_stage_id: uuid.UUID
    note: str | None
    changed_by: uuid.UUID | None
    changed_at: datetime

    model_config = {"from_attributes": True}


# ── Kanban Board ───────────────────────────────────────────────────────────────


class KanbanCard(BaseModel):
    application_id: uuid.UUID
    candidate_name: str | None
    candidate_email: str
    job_title: str
    company: str
    status: str
    entered_at: datetime


class KanbanColumn(BaseModel):
    stage_id: uuid.UUID
    stage_name: str
    stage_color: str | None
    position: int
    is_terminal: bool
    cards: list[KanbanCard]


class KanbanBoardRead(BaseModel):
    template_id: uuid.UUID
    template_name: str
    columns: list[KanbanColumn]
