"""Smart Organigramme API (Sprint 3.0).

Endpoints:
  GET    /org-charts                  – list all charts for current tenant
  POST   /org-charts                  – create new chart
  GET    /org-charts/{id}             – full chart (nodes + edges)
  PATCH  /org-charts/{id}             – update chart meta
  DELETE /org-charts/{id}             – delete chart
  PUT    /org-charts/{id}/save        – bulk-save entire state (atomic)
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import TenantRecruiterUser
from app.orgcharts.models import OrgChart, OrgEdge, OrgNode
from app.orgcharts.schemas import (
    BulkSavePayload,
    OrgChartCreate,
    OrgChartFull,
    OrgChartRead,
    OrgChartUpdate,
    OrgEdgeRead,
    OrgNodeRead,
)

router = APIRouter()

Db = Annotated[AsyncSession, Depends(get_db)]


async def _get_chart_or_404(
    db: AsyncSession, chart_id: uuid.UUID, tenant_id: uuid.UUID
) -> OrgChart:
    result = await db.execute(
        select(OrgChart).where(OrgChart.id == chart_id, OrgChart.tenant_id == tenant_id)
    )
    chart = result.scalar_one_or_none()
    if chart is None:
        raise HTTPException(status_code=404, detail="Organigramm nicht gefunden")
    return chart


# ── List / Create ──────────────────────────────────────────────────────────────


@router.get("", response_model=list[OrgChartRead], summary="Alle Organigramme des Tenants")
async def list_charts(current_user: TenantRecruiterUser, db: Db) -> list[OrgChartRead]:
    if not current_user.tenant_id:
        return []

    result = await db.execute(
        select(OrgChart)
        .where(OrgChart.tenant_id == current_user.tenant_id)
        .order_by(OrgChart.updated_at.desc())
    )
    charts = result.scalars().all()

    # Count nodes per chart
    counts_res = await db.execute(
        select(OrgNode.chart_id, func.count(OrgNode.id))
        .where(OrgNode.chart_id.in_([c.id for c in charts]))
        .group_by(OrgNode.chart_id)
    )
    count_map = {row[0]: row[1] for row in counts_res}

    out = []
    for c in charts:
        r = OrgChartRead.model_validate(c)
        r.node_count = count_map.get(c.id, 0)
        out.append(r)
    return out


@router.post("", response_model=OrgChartFull, status_code=201, summary="Organigramm erstellen")
async def create_chart(
    body: OrgChartCreate,
    current_user: TenantRecruiterUser,
    db: Db,
) -> OrgChartFull:
    if not current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Kein Tenant zugewiesen")

    chart = OrgChart(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        name=body.name,
        description=body.description,
        chart_type=body.chart_type,
    )
    db.add(chart)
    await db.commit()
    await db.refresh(chart)

    r = OrgChartFull.model_validate(chart)
    r.nodes = []
    r.edges = []
    return r


# ── Get / Update / Delete ──────────────────────────────────────────────────────


@router.get("/{chart_id}", response_model=OrgChartFull, summary="Organigramm laden")
async def get_chart(chart_id: uuid.UUID, current_user: TenantRecruiterUser, db: Db) -> OrgChartFull:
    chart = await _get_chart_or_404(db, chart_id, current_user.tenant_id)

    nodes_res = await db.execute(select(OrgNode).where(OrgNode.chart_id == chart_id))
    edges_res = await db.execute(select(OrgEdge).where(OrgEdge.chart_id == chart_id))

    nodes = [OrgNodeRead.from_orm_node(n) for n in nodes_res.scalars().all()]
    edges = [OrgEdgeRead.model_validate(e) for e in edges_res.scalars().all()]

    r = OrgChartFull.model_validate(chart)
    r.node_count = len(nodes)
    r.nodes = nodes
    r.edges = edges
    return r


@router.patch("/{chart_id}", response_model=OrgChartRead, summary="Chart-Meta bearbeiten")
async def update_chart(
    chart_id: uuid.UUID,
    body: OrgChartUpdate,
    current_user: TenantRecruiterUser,
    db: Db,
) -> OrgChartRead:
    chart = await _get_chart_or_404(db, chart_id, current_user.tenant_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(chart, field, value)
    await db.commit()
    await db.refresh(chart)
    return OrgChartRead.model_validate(chart)


@router.delete("/{chart_id}", status_code=204, summary="Organigramm löschen")
async def delete_chart(chart_id: uuid.UUID, current_user: TenantRecruiterUser, db: Db) -> None:
    chart = await _get_chart_or_404(db, chart_id, current_user.tenant_id)
    await db.delete(chart)
    await db.commit()


# ── Bulk Save (atomic) ─────────────────────────────────────────────────────────


@router.put("/{chart_id}/save", response_model=OrgChartFull, summary="Ganzen Chart-State speichern")
async def save_chart(
    chart_id: uuid.UUID,
    body: BulkSavePayload,
    current_user: TenantRecruiterUser,
    db: Db,
) -> OrgChartFull:
    """Atomically replace all nodes+edges for a chart.

    The frontend sends the full current state after every significant edit.
    Existing nodes/edges are deleted and recreated. Stable IDs (if provided)
    are preserved so the frontend can match server UUIDs.
    """
    chart = await _get_chart_or_404(db, chart_id, current_user.tenant_id)

    from app.jobs.models import JobPosting
    from app.users.models import User

    node_ids = {n.id for n in body.nodes if n.id is not None}
    if len(node_ids) != sum(n.id is not None for n in body.nodes):
        raise HTTPException(status_code=422, detail="Knoten-IDs müssen eindeutig sein.")
    edge_ids = [e.id for e in body.edges if e.id is not None]
    if len(set(edge_ids)) != len(edge_ids):
        raise HTTPException(status_code=422, detail="Verbindungs-IDs müssen eindeutig sein.")
    if any(e.source_id not in node_ids or e.target_id not in node_ids for e in body.edges):
        raise HTTPException(
            status_code=422, detail="Verbindungen müssen auf Knoten dieses Organigramms zeigen."
        )
    for model, identifiers in ((OrgNode, node_ids), (OrgEdge, set(edge_ids))):
        collision = await db.scalar(
            select(model.id).where(model.id.in_(identifiers), model.chart_id != chart_id).limit(1)
        )
        if collision:
            raise HTTPException(
                status_code=409,
                detail="Die IDs werden bereits in einem anderen Organigramm verwendet.",
            )
    person_ids = {n.person_id for n in body.nodes if n.person_id}
    job_ids = {n.job_posting_id for n in body.nodes if n.job_posting_id}
    for entity_model, identifiers in ((User, person_ids), (JobPosting, job_ids)):
        matching = await db.scalars(
            select(entity_model.id).where(
                entity_model.id.in_(identifiers), entity_model.tenant_id == current_user.tenant_id
            )
        )
        if set(matching.all()) != identifiers:
            raise HTTPException(
                status_code=404, detail="Person oder Stelle nicht in dieser Organisation gefunden."
            )
    await db.execute(select(OrgChart.id).where(OrgChart.id == chart_id).with_for_update())

    # Update meta if provided
    if body.name:
        chart.name = body.name
    if body.description is not None:
        chart.description = body.description

    # Build ID map: client-side UUID → server UUID
    # Clients may send their own UUIDs (stable between saves) or omit for new nodes

    # Delete all existing nodes (cascades to edges via FK)
    await db.execute(delete(OrgEdge).where(OrgEdge.chart_id == chart_id))
    await db.execute(delete(OrgNode).where(OrgNode.chart_id == chart_id))
    await db.flush()

    # Re-insert nodes
    node_id_map: dict[str, uuid.UUID] = {}
    for n in body.nodes:
        node_id = n.id if n.id else uuid.uuid4()
        node_id_map[str(n.id) if n.id else str(node_id)] = node_id
        db.add(
            OrgNode(
                id=node_id,
                chart_id=chart_id,
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
                metadata_=n.metadata,
            )
        )

    await db.flush()

    # Re-insert edges (resolve node IDs via map)
    for e in body.edges:
        db.add(
            OrgEdge(
                id=e.id if e.id else uuid.uuid4(),
                chart_id=chart_id,
                source_id=e.source_id,
                target_id=e.target_id,
                edge_type=e.edge_type,
                label=e.label,
            )
        )

    await db.commit()
    await db.refresh(chart)

    # Return full updated chart
    nodes_res = await db.execute(select(OrgNode).where(OrgNode.chart_id == chart_id))
    edges_res = await db.execute(select(OrgEdge).where(OrgEdge.chart_id == chart_id))

    nodes = [OrgNodeRead.from_orm_node(n) for n in nodes_res.scalars().all()]
    edges = [OrgEdgeRead.model_validate(e) for e in edges_res.scalars().all()]

    r = OrgChartFull.model_validate(chart)
    r.node_count = len(nodes)
    r.nodes = nodes
    r.edges = edges
    return r
