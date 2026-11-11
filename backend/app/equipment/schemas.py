"""Pydantic schemas for Equipment (Sprint 4.8)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

# ── Equipment Item ─────────────────────────────────────────────────────────────


class EquipmentItemCreate(BaseModel):
    name: str = Field(..., max_length=200)
    category: str = "other"
    serial_number: str | None = Field(None, max_length=100)
    asset_tag: str | None = Field(None, max_length=100)
    condition: str = "good"
    description: str | None = None
    notes: str | None = None


class EquipmentItemUpdate(BaseModel):
    name: str | None = Field(None, max_length=200)
    category: str | None = None
    serial_number: str | None = None
    asset_tag: str | None = None
    status: str | None = None
    condition: str | None = None
    description: str | None = None
    notes: str | None = None


class EquipmentItemRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    category: str
    serial_number: str | None
    asset_tag: str | None
    status: str
    condition: str
    description: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Assignment ────────────────────────────────────────────────────────────────


class AssignItemRequest(BaseModel):
    worker_id: uuid.UUID
    assigned_at: date
    notes: str | None = None


class ReturnItemRequest(BaseModel):
    returned_at: date
    notes: str | None = None


class EquipmentAssignmentRead(BaseModel):
    id: uuid.UUID
    equipment_item_id: uuid.UUID
    worker_id: uuid.UUID
    tenant_id: uuid.UUID
    assigned_by: uuid.UUID | None
    assigned_at: date
    returned_at: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    # Enriched
    item: EquipmentItemRead | None = None
    worker_name: str | None = None
    worker_email: str = ""
    assigned_by_name: str | None = None

    model_config = {"from_attributes": True}
