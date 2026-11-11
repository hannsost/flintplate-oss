from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class PlacementCreate(BaseModel):
    commission_pct: Decimal = Field(Decimal("27.50"), ge=0, le=100)
    annual_salary: int | None = Field(None, ge=0)
    notes: str | None = None


class PlacementRead(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID | None
    application_id: uuid.UUID
    recruiter_id: uuid.UUID
    candidate_name: str | None
    position_title: str | None
    company_name: str | None
    commission_pct: Decimal
    annual_salary: int | None
    commission_eur: Decimal | None
    notes: str | None
    placed_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class PlacementStats(BaseModel):
    total_placements: int
    total_commission_eur: Decimal
    avg_commission_eur: Decimal
    avg_commission_pct: Decimal
    placements_this_month: int
    commission_this_month: Decimal
