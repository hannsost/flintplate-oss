"""Separate private review data from candidate-visible offers and tasks."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OfferContent(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    terms: str = Field(min_length=10, max_length=20000)
    start_date: date
    expires_on: date

    @model_validator(mode="after")
    def valid_dates(self) -> OfferContent:
        if self.expires_on < date.today() or self.start_date < self.expires_on:
            raise ValueError(
                "Das Ablaufdatum muss zwischen heute und dem geplanten Eintritt liegen."
            )
        return self


class OfferCreate(OfferContent):
    application_id: uuid.UUID


class OfferEdit(OfferContent):
    version: int = Field(ge=1)


class OfferAction(BaseModel):
    action: Literal["submit", "approve", "changes", "share", "withdraw"]
    version: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=2000)
    approver_id: uuid.UUID | None = None


class OfferDecision(BaseModel):
    decision: Literal["accepted", "declined"]
    version: int = Field(ge=1)


class OfferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    application_id: uuid.UUID
    title: str
    terms: str
    start_date: date
    expires_on: date
    status: str
    version: int
    shared_at: datetime | None
    created_at: datetime


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    actor_id: uuid.UUID | None
    status: str
    version: int
    note: str | None
    title: str
    terms: str
    start_date: date
    expires_on: date
    created_at: datetime


class OfferPrivate(OfferRead):
    person_id: uuid.UUID
    person_name: str
    created_by: uuid.UUID | None
    approver_id: uuid.UUID | None
    events: list[EventRead]


class TemplateStep(BaseModel):
    title: str
    audience: Literal["hr", "person"]
    days_from_start: int


class TemplateRead(BaseModel):
    key: str
    title: str
    steps: list[TemplateStep]


class CaseCreate(BaseModel):
    offer_id: uuid.UUID
    template: Literal["internal_hr", "agency", "staffing"]
    owner_id: uuid.UUID


class StepEdit(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    audience: Literal["hr", "person"]
    assignee_id: uuid.UUID | None = None
    due_on: date


class Completion(BaseModel):
    completed: bool


class StepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    audience: str
    assignee_id: uuid.UUID | None
    due_on: date
    completed_at: datetime | None
    completed_by: uuid.UUID | None


class CaseRead(BaseModel):
    id: uuid.UUID
    offer_id: uuid.UUID
    person_id: uuid.UUID
    person_name: str
    title: str
    owner_id: uuid.UUID | None
    start_date: date
    template: str
    activated_at: datetime | None
    completed: int
    total: int
    steps: list[StepRead]


class TeamOption(BaseModel):
    id: uuid.UUID
    full_name: str
    role: str


class Activation(BaseModel):
    employment_type: Literal["fulltime", "parttime", "minijob", "temp"]
    confirmed: Literal[True]


class ApprovalPolicy(BaseModel):
    self_approval_allowed: bool
