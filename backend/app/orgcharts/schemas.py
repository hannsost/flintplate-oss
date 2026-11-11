"""Pydantic schemas for Organigramme."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ── OrgChart ───────────────────────────────────────────────────────────────────


class OrgChartCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    chart_type: str = Field("hierarchical", pattern=r"^(hierarchical|matrix|flat|divisional)$")


class OrgChartUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    chart_type: str | None = None


class OrgChartRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str | None
    chart_type: str
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    node_count: int = 0

    model_config = {"from_attributes": True}


# ── OrgNode ────────────────────────────────────────────────────────────────────


class OrgNodeWrite(BaseModel):
    """Used for both create and upsert in bulk-save."""

    id: uuid.UUID | None = None  # None = new node
    title: str = Field(..., min_length=1, max_length=255)
    department: str | None = None
    person_name: str | None = None
    person_email: str | None = None
    person_id: uuid.UUID | None = None
    job_posting_id: uuid.UUID | None = None
    status: str = Field("open", pattern=r"^(filled|open|temp|contractor|planned)$")
    pos_x: float = 0.0
    pos_y: float = 0.0
    node_width: float = 200.0
    node_height: float = 80.0
    color: str | None = None
    metadata: dict[str, Any] | None = None


class OrgNodeRead(BaseModel):
    id: uuid.UUID
    chart_id: uuid.UUID
    title: str
    department: str | None
    person_name: str | None
    person_email: str | None
    person_id: uuid.UUID | None
    job_posting_id: uuid.UUID | None
    status: str
    pos_x: float
    pos_y: float
    node_width: float
    node_height: float
    color: str | None
    metadata: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_node(cls, n: Any) -> OrgNodeRead:
        return cls(
            id=n.id,
            chart_id=n.chart_id,
            title=n.title,
            department=n.department,
            person_name=n.person_name,
            person_email=n.person_email,
            person_id=n.person_id,
            job_posting_id=n.job_posting_id,
            status=n.status,
            pos_x=n.pos_x,
            pos_y=n.pos_y,
            node_width=n.node_width,
            node_height=n.node_height,
            color=n.color,
            metadata=n.metadata_,
            created_at=n.created_at,
            updated_at=n.updated_at,
        )


# ── OrgEdge ────────────────────────────────────────────────────────────────────


class OrgEdgeWrite(BaseModel):
    id: uuid.UUID | None = None
    source_id: uuid.UUID
    target_id: uuid.UUID
    edge_type: str = Field("solid", pattern=r"^(solid|dotted|functional)$")
    label: str | None = None


class OrgEdgeRead(BaseModel):
    id: uuid.UUID
    chart_id: uuid.UUID
    source_id: uuid.UUID
    target_id: uuid.UUID
    edge_type: str
    label: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Full chart payload ─────────────────────────────────────────────────────────


class OrgChartFull(OrgChartRead):
    nodes: list[OrgNodeRead] = []
    edges: list[OrgEdgeRead] = []


class BulkSavePayload(BaseModel):
    """Atomic save of the entire chart state from the frontend editor."""

    nodes: list[OrgNodeWrite]
    edges: list[OrgEdgeWrite]
    # Optionally update chart meta at the same time
    name: str | None = None
    description: str | None = None
