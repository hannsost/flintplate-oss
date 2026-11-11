from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Capability = Literal["job_check", "onboarding_draft", "ai_job_brief"]


class AgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    owner_id: uuid.UUID
    enabled: bool = False
    capability: Capability
    daily_task_limit: int = Field(default=20, ge=1, le=1000)
    max_attempts: int = Field(default=3, ge=1, le=3)
    four_eyes: bool = True

    @model_validator(mode="after")
    def ai_attempt_limit(self) -> AgentInput:
        if self.capability == "ai_job_brief" and self.max_attempts != 1:
            raise ValueError(
                "Externe KI-Aufrufe benötigen max_attempts=1; unklare Zustellung wird nicht automatisch wiederholt."
            )
        return self


class AgentUpdate(AgentInput):
    expected_version: int = Field(ge=1)


class AgentRead(BaseModel):
    id: uuid.UUID
    name: str
    owner_id: uuid.UUID | None
    enabled: bool
    version: int
    capability: str
    daily_task_limit: int
    max_attempts: int
    four_eyes: bool


class TaskAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: int = Field(ge=1)
    job_id: uuid.UUID
    reviewer_id: uuid.UUID
    title: str = Field(min_length=1, max_length=300)
    instructions: str = Field(default="", max_length=3000)
    authorize_ai: bool = False
    request_key: uuid.UUID


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    agent_id: uuid.UUID
    task_id: uuid.UUID
    job_id: uuid.UUID
    delegated_by: uuid.UUID | None
    reviewer_id: uuid.UUID | None
    status: str
    version: int
    source: dict[str, str]
    output: str | None
    output_origin: str | None
    provider_model: str | None
    review_note: str | None
    reviewed_at: datetime | None
    created_at: datetime
    queue_status: str
    attempts: int
    max_attempts: int
    last_error_code: str | None


class RunReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: int = Field(ge=1)
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=5, max_length=2000)
