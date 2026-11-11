"""Company schemas – Sprint 1.2."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CompanyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    workspace_type: Literal["internal_hr", "recruiter_agency", "solo_recruiter", "zeitarbeit"] = (
        "recruiter_agency"
    )
    website: str | None = None
    description: str | None = None
    location: str | None = None
    logo_url: str | None = None


class CompanyUpdate(BaseModel):
    name: str | None = None
    website: str | None = None
    description: str | None = None
    location: str | None = None
    logo_url: str | None = None


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    website: str | None
    description: str | None
    location: str | None
    logo_url: str | None
    created_at: datetime
