"""Pydantic schemas for Support module."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

# ── Config ────────────────────────────────────────────────────────────────────


class SupportConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    enabled: bool
    allow_video: bool
    allow_audio: bool
    allow_remote_control: bool
    allow_dom_viewing: bool
    billing_model: str
    per_session_cents: int | None
    per_minute_cents: int | None
    included_minutes_per_month: int | None
    widget_title: str
    widget_color: str
    welcome_message: str | None
    mask_sensitive_fields: bool
    require_consent: bool
    data_retention_days: int
    updated_at: datetime


class SupportConfigUpdate(BaseModel):
    enabled: bool | None = None
    allow_video: bool | None = None
    allow_audio: bool | None = None
    allow_remote_control: bool | None = None
    allow_dom_viewing: bool | None = None
    billing_model: str | None = None
    per_session_cents: int | None = None
    per_minute_cents: int | None = None
    included_minutes_per_month: int | None = None
    widget_title: str | None = None
    widget_color: str | None = None
    welcome_message: str | None = None
    mask_sensitive_fields: bool | None = None
    require_consent: bool | None = None
    data_retention_days: int | None = None


# ── Session ───────────────────────────────────────────────────────────────────


class SupportSessionCreate(BaseModel):
    subject: str
    video_enabled: bool = False
    audio_enabled: bool = False
    remote_control_enabled: bool = False
    dom_viewing_enabled: bool = False


class SupportSessionRead(BaseModel):
    """Public session view – agent_notes omitted."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    requester_id: uuid.UUID
    agent_id: uuid.UUID | None
    status: str
    subject: str
    consent_given: bool
    consent_given_at: datetime | None
    requested_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int | None
    video_enabled: bool
    audio_enabled: bool
    remote_control_enabled: bool
    dom_viewing_enabled: bool
    billing_model: str
    billed_amount_cents: int | None
    summary: str | None
    end_reason: str | None
    created_at: datetime


class SupportSessionAgentRead(SupportSessionRead):
    """Extended view for support agents – includes agent_notes."""

    agent_notes: str | None


class SupportSessionUpdate(BaseModel):
    """Allowed updates (agent only)."""

    agent_notes: str | None = None
    summary: str | None = None


class SupportSessionConsentResponse(BaseModel):
    ok: bool


# ── Widget config (public, minimal) ──────────────────────────────────────────


class SupportWidgetConfig(BaseModel):
    """Minimal config returned to the widget (no billing details)."""

    enabled: bool
    allow_video: bool
    allow_audio: bool
    allow_remote_control: bool
    allow_dom_viewing: bool
    widget_title: str
    widget_color: str
    welcome_message: str | None
    require_consent: bool
