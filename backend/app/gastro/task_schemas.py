"""Venue tasks use existing human tasks and an explicit revisioned command API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Priority = Literal["low", "medium", "high", "urgent"]
Status = Literal["open", "in_progress", "done", "cancelled"]
Action = Literal["start", "done", "cancel", "reopen", "reassign", "edit"]


class TaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class VenueTaskCreate(TaskInput):
    request_key: uuid.UUID
    assigned_to: uuid.UUID
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=4000)
    due_at: AwareDatetime | None = None
    priority: Priority = "medium"
    require_completion_note: bool = False


class VenueTaskAction(TaskInput):
    request_key: uuid.UUID
    version: int = Field(ge=1)
    action: Action
    note: str = Field(default="", max_length=1000)
    assigned_to: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    due_at: AwareDatetime | None = None
    priority: Priority | None = None
    require_completion_note: bool | None = None

    @model_validator(mode="after")
    def action_fields(self) -> Self:
        if self.action not in {"start", "done"} and len(self.note) < 3:
            raise ValueError("Diese Leitungsaktion benötigt eine Begründung.")
        edits = {"title", "description", "due_at", "priority", "require_completion_note"}
        if self.action == "reassign":
            if self.assigned_to is None or self.model_fields_set & edits:
                raise ValueError("Neuzuweisung benötigt ausschließlich die neue Person.")
        elif self.action == "edit":
            if (
                self.assigned_to is not None
                or not edits <= self.model_fields_set
                or self.title is None
                or self.description is None
                or self.priority is None
                or self.require_completion_note is None
            ):
                raise ValueError(
                    "Bearbeitung benötigt Titel, Beschreibung, Fälligkeit und Priorität."
                )
        elif self.assigned_to is not None or self.model_fields_set & edits:
            raise ValueError("Dieser Statuswechsel darf keine Aufgabenstammdaten ändern.")
        return self


class VenueTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    venue_id: uuid.UUID
    title: str
    description: str | None
    assigned_to: uuid.UUID
    assigned_to_name: str
    assigned_by: uuid.UUID | None
    assigned_by_name: str | None
    due_at: datetime | None
    priority: Priority
    require_completion_note: bool
    status: Status
    version: int
    worker_note: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class VenueTaskPage(BaseModel):
    items: list[VenueTaskRead]
    next_before: uuid.UUID | None
    has_more: bool


class TaskCommandRead(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    actor_id: uuid.UUID
    actor_name: str
    kind: str
    note: str
    before: VenueTaskRead | None
    after: VenueTaskRead
    created_at: datetime


class TaskHistoryPage(BaseModel):
    items: list[TaskCommandRead]
    next_before: uuid.UUID | None
    has_more: bool
