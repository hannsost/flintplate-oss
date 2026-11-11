"""Cover letter schemas – Sprint 0.6."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CoverLetterRequest(BaseModel):
    """Request body for cover letter generation."""

    # Either provide a job_id (from our DB) or free-text fields
    job_id: uuid.UUID | None = None
    company: str = Field(max_length=255)
    position: str = Field(max_length=500)
    job_description: str | None = Field(default=None, max_length=5000)
    company_context: str | None = Field(default=None, max_length=2000)
    tone: str = Field(default="professionell", max_length=50)
    application_id: uuid.UUID | None = None


class CVAdjustRequest(BaseModel):
    job_id: uuid.UUID | None = None
    company: str = Field(max_length=255)
    position: str = Field(max_length=500)
    job_description: str | None = Field(default=None, max_length=5000)


class CoverLetterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    job_id: uuid.UUID | None
    application_id: uuid.UUID | None
    company: str
    position: str
    tone: str
    generated_text: str
    model_used: str
    ai_generated: bool
    created_at: datetime


class CVAdjustResponse(BaseModel):
    highlighted_skills: list[str]
    highlighted_experience_ids: list[str]
    suggested_summary: str
    tips: list[str]
    model_used: str
    ai_generated: bool
    disclaimer: str
