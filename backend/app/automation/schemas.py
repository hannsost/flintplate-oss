from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: Literal["job_check", "message_draft", "ai_job_brief", "internal_notification"]
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(default="", max_length=2000)
    mode: Literal["automatic", "review"] = "review"

    @model_validator(mode="after")
    def enforce_review(self) -> Self:
        if self.action in {"message_draft", "ai_job_brief"} and self.mode != "review":
            raise ValueError("KI-Ergebnisse und Nachrichtenentwürfe benötigen eine Prüfung.")
        if self.action in {"message_draft", "internal_notification"} and not self.text:
            raise ValueError("Für diesen Schritt ist ein Text erforderlich.")
        return self


class TemplateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    enabled: bool = False
    four_eyes: bool = True
    steps: list[Step] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def ai_budget(self) -> Self:
        if sum(step.action == "ai_job_brief" for step in self.steps) > 1:
            raise ValueError("Pro Prozess ist maximal ein KI-Aufruf erlaubt.")
        return self


class TemplateUpdate(TemplateInput):
    version: int = Field(ge=1)


class TemplateRead(TemplateInput):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    version: int
    updated_at: datetime


class StartRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: uuid.UUID
    request_key: uuid.UUID
    template_version: int = Field(ge=1)
    authorize_ai: bool = False


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version: int = Field(ge=1)
    decision: Literal["approve", "reject", "cancel"]
    note: str = Field(min_length=3, max_length=2000)


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    actor_id: uuid.UUID | None
    action: str
    step: int
    note: str
    created_at: datetime


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    template_id: uuid.UUID
    template_version: int
    job_id: uuid.UUID
    created_by: uuid.UUID | None
    name: str
    status: str
    version: int
    cursor: int
    four_eyes: bool
    source: dict[str, str]
    steps: list[Step]
    results: list[dict[str, object]]
    created_at: datetime
    events: list[EventRead] = Field(default_factory=list)
