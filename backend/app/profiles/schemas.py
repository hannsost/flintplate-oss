"""Pydantic v2 schemas for candidate profiles – Sprint 0.2."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _coerce_date(v: Any) -> date | None:
    """Accept full dates, YYYY-MM, or YYYY strings in addition to date objects."""
    if v is None or isinstance(v, date):
        return v
    if not isinstance(v, str):
        return None
    v = v.strip()
    if not v:
        return None
    # YYYY-MM-DD
    if len(v) == 10:
        return date.fromisoformat(v)
    # YYYY-MM → first day of month
    if len(v) == 7:
        return date.fromisoformat(f"{v}-01")
    # YYYY → Jan 1
    if len(v) == 4 and v.isdigit():
        return date.fromisoformat(f"{v}-01-01")
    return None


# ── Work Experience ───────────────────────────────────────────────────────────


class WorkExperienceBase(BaseModel):
    company: str = Field(max_length=255)
    title: str = Field(max_length=255)
    location: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = False
    description: str | None = None

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def coerce_date(cls, v: Any) -> date | None:
        return _coerce_date(v)


class WorkExperienceCreate(WorkExperienceBase):
    pass


class WorkExperienceRead(WorkExperienceBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    profile_id: uuid.UUID
    source: str | None = None
    created_at: datetime


# ── Education ─────────────────────────────────────────────────────────────────


class EducationBase(BaseModel):
    institution: str = Field(max_length=255)
    degree: str | None = None
    field_of_study: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    grade: str | None = None

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def coerce_date(cls, v: Any) -> date | None:
        return _coerce_date(v)


class EducationCreate(EducationBase):
    pass


class EducationRead(EducationBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    profile_id: uuid.UUID
    source: str | None = None
    created_at: datetime


# ── Skill ─────────────────────────────────────────────────────────────────────


class SkillBase(BaseModel):
    name: str = Field(max_length=100)
    category: str | None = None
    level: str | None = Field(
        default=None,
        max_length=50,
        description="beginner | intermediate | advanced | expert",
    )
    years_of_experience: int | None = Field(default=None, ge=0, le=50)


class SkillCreate(SkillBase):
    pass


class SkillRead(SkillBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    profile_id: uuid.UUID
    source: str | None = None
    created_at: datetime


# ── CandidateProfile ──────────────────────────────────────────────────────────


class ProfileCreate(BaseModel):
    headline: str | None = Field(default=None, max_length=255)
    summary: str | None = None
    location: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    website: str | None = None
    linkedin_url: str | None = None


class ProfileUpdate(BaseModel):
    headline: str | None = Field(default=None, max_length=255)
    summary: str | None = None
    location: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    website: str | None = None
    linkedin_url: str | None = None
    work_experiences: list[WorkExperienceCreate] | None = None
    educations: list[EducationCreate] | None = None
    skills: list[SkillCreate] | None = None


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    headline: str | None
    summary: str | None
    location: str | None
    phone: str | None
    website: str | None
    linkedin_url: str | None
    cv_original_filename: str | None
    completeness_score: int
    structured_data: dict[str, Any] | None
    work_experiences: list[WorkExperienceRead]
    educations: list[EducationRead]
    skills: list[SkillRead]
    created_at: datetime
    updated_at: datetime


class CVUploadResponse(BaseModel):
    """Response after CV upload + mock parse."""

    profile: ProfileRead
    parse_status: str  # "parsed" | "queued" | "failed"
    extracted_fields: dict[str, Any]
