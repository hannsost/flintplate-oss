"""Pydantic schemas for job postings – Sprint 0.4."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field


def safe_job_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError(
            "Stellenlinks müssen HTTP(S) verwenden und dürfen keine Zugangsdaten enthalten."
        )
    return value


JobURL = Annotated[str, Field(max_length=1000), AfterValidator(safe_job_url)]


class JobPostingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=500)
    company: str = Field(min_length=1, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=100000)
    url: JobURL | None = None
    is_remote: bool = False
    salary_min: int | None = None
    salary_max: int | None = None
    required_skills: list[str] = Field(default_factory=list)
    employment_type: str | None = None
    source: str = Field(default="mock", max_length=100)
    external_id: str | None = Field(default=None, max_length=255)
    posted_at: datetime | None = None


class JobPostingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    company: str
    location: str | None
    description: str | None
    url: str | None
    is_remote: bool
    salary_min: int | None
    salary_max: int | None
    required_skills: list[str]
    employment_type: str | None
    category: str | None
    source: str
    posted_at: datetime | None
    created_at: datetime
    publication_status: str
    version: int
    published_at: datetime | None
    expires_at: datetime | None
    archived_at: datetime | None


class JobMatchRequest(BaseModel):
    """Request body for POST /jobs/match."""

    job_id: uuid.UUID
    profile_id: uuid.UUID | None = None  # None → use caller's own profile


class JobMatchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job: JobPostingRead
    score: float = Field(ge=0.0, le=100.0, description="Match score 0–100")
    vector_similarity: float | None
    skill_overlap: float | None
    explanation: dict[str, Any] | None


class JobFeedResponse(BaseModel):
    jobs: list[JobMatchResult]
    total: int
    page: int
    page_size: int


class JobPostingUpdate(BaseModel):
    """For recruiter PATCH – all fields optional."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    company: str | None = Field(default=None, min_length=1, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=100000)
    url: JobURL | None = None
    is_remote: bool | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    required_skills: list[str] | None = None
    employment_type: str | None = None


class JobPublicationChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    expires_at: AwareDatetime | None = None
    rights_confirmed: bool = False
    note: str | None = Field(default=None, max_length=1000)


class JobPublicationEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    actor_id: uuid.UUID | None
    version: int
    action: str
    note: str | None
    created_at: datetime


class CandidateMatchRead(BaseModel):
    """A candidate matched to a recruiter's job posting."""

    model_config = ConfigDict(from_attributes=True)

    profile_id: uuid.UUID
    full_name: str | None
    headline: str | None
    location: str | None
    score: float
    skill_overlap_pct: float
    matched_skills: list[str]
    missing_skills: list[str]
    passed_gate: bool  # True if meets hard requirements


class RecruiterApplicationRead(BaseModel):
    """A candidate's application as seen by a recruiter."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    candidate_name: str | None
    candidate_headline: str | None
    candidate_location: str | None
    status: str
    applied_at: datetime | None
    notes: str | None
    created_at: datetime
    # Pipeline Builder: current stage assignment (null if not assigned)
    pipeline_stage_id: uuid.UUID | None = None
    pipeline_stage_name: str | None = None
    pipeline_stage_color: str | None = None


class RecruiterApplicationUpdate(BaseModel):
    """Recruiter moves a candidate through the pipeline."""

    status: str
    note: str | None = None


class SalaryStat(BaseModel):
    category: str
    count: int
    salary_min_avg: float | None
    salary_max_avg: float | None
    salary_mid: float | None  # midpoint average


class MarketStats(BaseModel):
    total_jobs: int
    remote_count: int
    remote_pct: float
    top_skills: list[dict[str, Any]]  # [{"skill": str, "count": int, "pct": float}]
    categories: list[dict[str, Any]]  # [{"category": str, "count": int, "pct": float}]
    salary_by_category: list[SalaryStat]
    employment_types: list[dict[str, Any]]  # [{"type": str, "count": int}]


class SkillGap(BaseModel):
    skill: str
    market_demand_pct: float  # % of jobs requiring this skill
    course_url: str | None  # suggested learning resource
    # v2 fields
    category: str | None = None  # skill category (Frontend, Backend, DevOps…)
    difficulty: str | None = None  # beginner / intermediate / advanced
    est_hours: int | None = None  # estimated learning hours
    priority_score: float = 0.0  # demand × (1/difficulty_factor) → sort key


class LearningPath(BaseModel):
    category: str
    skills: list[SkillGap]
    total_hours: int


class ProfileGapAnalysis(BaseModel):
    my_skills: list[str]
    top_gaps: list[SkillGap]  # skills I don't have, sorted by demand
    coverage_pct: float  # % of top-50 skills I already have
    strong_skills: list[str]  # skills I have that are highly demanded
    # v2 fields
    learning_paths: list[LearningPath] = []  # gaps grouped by category


class JobFilter(BaseModel):
    """Query filters for GET /jobs/recommended."""

    remote_only: bool = False
    min_salary: int | None = None
    skills: list[str] = Field(default_factory=list)
    location: str | None = None
    category: str | None = None
    text_search: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


# ── Job Alert schemas (Sprint 2.0) ────────────────────────────────────────────


class JobAlertCreate(BaseModel):
    keywords: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    remote_only: bool = False
    min_salary: int | None = None
    category: str | None = Field(default=None, max_length=50)
    min_score: int = Field(default=60, ge=0, le=100)


class JobAlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    keywords: str | None
    location: str | None
    remote_only: bool
    min_salary: int | None
    category: str | None
    min_score: int
    is_active: bool
    last_sent_at: datetime | None
    created_at: datetime
