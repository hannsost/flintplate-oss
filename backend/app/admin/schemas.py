"""Pydantic schemas for Admin Hub."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

# ── Customer ───────────────────────────────────────────────────────────────────


class CustomerCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: str = Field(..., min_length=2, max_length=100, pattern=r"^[a-z0-9\-]+$")
    type: str = Field(
        "recruiter_agency", pattern=r"^(internal_hr|zeitarbeit|recruiter_agency|solo_recruiter)$"
    )
    plan: str = Field("starter", pattern=r"^(free|starter|professional|enterprise)$")
    status: str = Field("trial", pattern=r"^(trial|active|suspended|churned)$")
    contact_email: EmailStr | None = None
    contact_name: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    country: str = "DE"
    notes: str | None = None
    trial_ends_at: datetime | None = None
    contract_start: datetime | None = None
    contract_end: datetime | None = None


class CustomerUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=255)
    type: str | None = Field(
        None, pattern=r"^(internal_hr|zeitarbeit|recruiter_agency|solo_recruiter)$"
    )
    plan: str | None = Field(None, pattern=r"^(free|starter|professional|enterprise)$")
    status: str | None = Field(None, pattern=r"^(trial|active|suspended|churned)$")
    contact_email: EmailStr | None = None
    contact_name: str | None = Field(None, min_length=2, max_length=255)
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    notes: str | None = None
    trial_ends_at: datetime | None = None
    contract_start: datetime | None = None
    contract_end: datetime | None = None
    primary_color: str | None = None
    logo_url: str | None = None


class SetCustomDomain(BaseModel):
    custom_domain: str | None = None  # None = clear domain


class CustomerRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    type: str
    plan: str
    status: str
    contact_email: str | None
    contact_name: str | None
    phone: str | None
    address: str | None
    city: str | None
    country: str
    notes: str | None
    trial_ends_at: datetime | None
    contract_start: datetime | None
    contract_end: datetime | None
    created_at: datetime
    updated_at: datetime
    # Stripe (Sprint 2.3)
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    # White-Label (Sprint 2.6)
    custom_domain: str | None = None
    primary_color: str | None = None
    logo_url: str | None = None
    # Aggregated fields (populated on list endpoint)
    user_count: int = 0
    modules: list[str] = []

    model_config = {"from_attributes": True}


# ── CustomerModule ─────────────────────────────────────────────────────────────


class ModuleToggle(BaseModel):
    enabled: bool
    usage_limit: int | None = Field(None, ge=0)
    expires_at: datetime | None = None


class ModuleRead(BaseModel):
    module_key: str
    enabled: bool
    usage_limit: int | None
    usage_current: int
    activated_at: datetime
    expires_at: datetime | None

    model_config = {"from_attributes": True}


# ── Admin Analytics ────────────────────────────────────────────────────────────


class ModuleUsage(BaseModel):
    module_key: str
    count: int = Field(ge=0)


class AdminStats(BaseModel):
    total_customers: int
    active_customers: int
    trial_customers: int
    suspended_customers: int
    by_type: dict[str, int]
    by_plan: dict[str, int]
    top_modules: list[ModuleUsage]


# ── Assign user to tenant ──────────────────────────────────────────────────────


class AssignTenant(BaseModel):
    user_id: uuid.UUID
    tenant_id: uuid.UUID | None  # None = remove from tenant
