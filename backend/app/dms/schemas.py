"""Pydantic schemas for DMS (Sprint 3.1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ── DocCategory ───────────────────────────────────────────────────────────────


class DocCategoryRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID | None
    name: str
    slug: str
    color: str
    icon: str
    sort_order: int
    is_system: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class DocCategoryCreate(BaseModel):
    name: str = Field(..., max_length=100)
    slug: str = Field(..., max_length=50)
    color: str = Field("#6b7280", max_length=7)
    icon: str = Field("📄", max_length=10)
    sort_order: int = 0


class DocCategoryUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    color: str | None = Field(None, max_length=7)
    icon: str | None = Field(None, max_length=10)
    sort_order: int | None = None


# ── Document ──────────────────────────────────────────────────────────────────


class DocumentRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_by: uuid.UUID | None
    name: str
    original_filename: str
    file_url: str
    mime_type: str
    file_size: int
    checksum: str | None
    category_id: uuid.UUID | None
    tags: list[str] | None
    description: str | None
    is_template: bool
    linked_entity_type: str | None
    linked_entity_id: uuid.UUID | None
    version_number: int
    parent_document_id: uuid.UUID | None
    is_latest_version: bool
    visibility: str
    share_token: str | None
    share_expires_at: datetime | None
    expires_at: datetime | None
    expires_reminder_days: int
    thumbnail_url: str | None
    processing_status: str
    status: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    # category is injected by router when fetching
    category: DocCategoryRead | None = None

    model_config = {"from_attributes": True}


class DocumentCreate(BaseModel):
    name: str = Field(..., max_length=500)
    original_filename: str = Field(..., max_length=500)
    file_url: str = Field(..., max_length=1000)
    mime_type: str = Field(..., max_length=100)
    file_size: int = 0
    checksum: str | None = None
    category_id: uuid.UUID | None = None
    tags: list[str] | None = None
    description: str | None = None
    is_template: bool = False
    linked_entity_type: str | None = None
    linked_entity_id: uuid.UUID | None = None
    visibility: str = "tenant"
    expires_at: datetime | None = None
    expires_reminder_days: int = 30


class DocumentUpdate(BaseModel):
    name: str | None = Field(None, max_length=500)
    category_id: uuid.UUID | None = None
    tags: list[str] | None = None
    description: str | None = None
    visibility: str | None = None
    expires_at: datetime | None = None
    expires_reminder_days: int | None = None
    status: str | None = None


class DocumentPresignRequest(BaseModel):
    filename: str = Field(..., max_length=500)
    mime_type: str = Field(..., max_length=100)
    file_size: int = Field(..., gt=0)


class DocumentPresignResponse(BaseModel):
    upload_url: str
    file_url: str
    # pre-filled fields for the subsequent DocumentCreate call
    original_filename: str
    mime_type: str
    file_size: int


# ── DocShare ──────────────────────────────────────────────────────────────────


class DocShareRead(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    shared_by: uuid.UUID | None
    share_token: str
    shared_with_email: str | None
    access_type: str
    expires_at: datetime | None
    accessed_count: int
    last_accessed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocShareCreate(BaseModel):
    shared_with_email: str | None = None
    access_type: str = "view"
    expires_at: datetime | None = None
    password: str | None = None  # plain text, hashed in service


# ── DocActivity ───────────────────────────────────────────────────────────────


class DocActivityRead(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    user_id: uuid.UUID | None
    action: str
    metadata_: dict[str, Any] | None = None
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


# ── DocComment ────────────────────────────────────────────────────────────────


class DocCommentRead(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    user_id: uuid.UUID | None
    content: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocCommentCreate(BaseModel):
    content: str = Field(..., min_length=1)


# ── Composite ─────────────────────────────────────────────────────────────────


class DocumentDetail(DocumentRead):
    shares: list[DocShareRead] = []
    activity: list[DocActivityRead] = []
    comments: list[DocCommentRead] = []
    versions: list[DocumentRead] = []


class ExpiryDashboard(BaseModel):
    overdue: list[DocumentRead]
    expiring_soon: list[DocumentRead]  # within next 30 days
    ok: list[DocumentRead]


class BulkDownloadRequest(BaseModel):
    document_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=50)
