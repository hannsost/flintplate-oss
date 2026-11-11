from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

# ── Work Assignment ───────────────────────────────────────────────────────────

ASSIGNMENT_STATUSES = ["incoming", "matching", "active", "extended", "completed", "cancelled"]


class AssignmentCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    description: str | None = None
    required_skills: list[str] = []
    location: str | None = None
    shift: str | None = None  # day / night / flexible
    hourly_rate: Decimal | None = None
    start_date: date | None = None
    end_date: date | None = None
    company_id: uuid.UUID | None = None
    max_duration_months: int = Field(18, ge=1, le=18)
    notes: str | None = None


class AssignmentUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    required_skills: list[str] | None = None
    location: str | None = None
    shift: str | None = None
    hourly_rate: Decimal | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = None
    notes: str | None = None


class AssignmentRead(BaseModel):
    id: uuid.UUID
    recruiter_id: uuid.UUID
    company_id: uuid.UUID | None
    title: str
    description: str | None
    required_skills: list[str]
    location: str | None
    shift: str | None
    hourly_rate: Decimal | None
    start_date: date | None
    end_date: date | None
    status: str
    max_duration_months: int
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Temp Worker Availability ──────────────────────────────────────────────────


class AvailabilityUpsert(BaseModel):
    is_in_pool: bool = False
    available_from: date | None = None
    available_until: date | None = None
    preferred_shift: str | None = None
    preferred_location: str | None = None
    max_commute_km: int | None = Field(None, ge=0, le=500)
    notes: str | None = None


class AvailabilityRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    is_in_pool: bool
    available_from: date | None
    available_until: date | None
    preferred_shift: str | None
    preferred_location: str | None
    max_commute_km: int | None
    total_placed_months: Decimal
    notes: str | None
    updated_at: datetime
    # Computed compliance fields
    aueg_remaining_months: Decimal
    aueg_status: str  # green / yellow / red

    model_config = {"from_attributes": True}


# ── Disposition ───────────────────────────────────────────────────────────────


class DispositionRead(BaseModel):
    id: uuid.UUID
    assignment_id: uuid.UUID
    worker_id: uuid.UUID
    worker_name: str | None
    worker_headline: str | None
    score: Decimal
    matched_skills: list[str]
    missing_skills: list[str]
    status: str
    started_at: date | None
    ended_at: date | None
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DispositionUpdate(BaseModel):
    status: Literal["suggested", "confirmed", "active", "completed", "rejected", "cancelled"]
    started_at: date | None = None
    ended_at: date | None = None
    notes: str | None = None


class ZeitarbeitStats(BaseModel):
    total_assignments: int
    active_assignments: int
    workers_in_pool: int
    total_dispositions: int
    active_dispositions: int
    avg_fill_score: Decimal


# ── Workforce Canvas ───────────────────────────────────────────────────────────


class PoolWorkerRead(BaseModel):
    """Kompakte Worker-Karte für den Canvas Pool-Panel."""

    user_id: uuid.UUID
    full_name: str | None
    headline: str | None
    location: str | None
    aueg_remaining_months: Decimal
    aueg_status: str  # green / yellow / red
    total_placed_months: Decimal
    preferred_shift: str | None
    skills: list[str]

    model_config = {"from_attributes": True}


class JobCanvasRead(BaseModel):
    """Job-first Perspektive: Auftrag + gerankte Dispositions-Karten."""

    assignment: AssignmentRead
    dispositions: list[DispositionRead]
    pool_size: int  # Gesamtgröße des Pools zum Vergleich


class WorkerCanvasRead(BaseModel):
    """Worker-first Perspektive: Pool-Worker + aktive & empfohlene Aufträge."""

    worker: PoolWorkerRead
    active_assignments: list[AssignmentRead]
    recommended_assignments: list[AssignmentRead]


class CanvasAssignPayload(BaseModel):
    assignment_id: uuid.UUID
    worker_id: uuid.UUID
    # Optionaler Status beim Zuweisen (default: confirmed)
    status: Literal["confirmed", "active"] = "confirmed"
