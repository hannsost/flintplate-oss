"""HR endpoints for work assignment management (Sprint 4.3).

Mounted at /zeitarbeit/assignments
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.dependencies import DBSession, TenantRecruiterUser
from app.users.models import User
from app.worker.assignment_models import ASSIGNMENT_STATUSES
from app.worker.assignment_models import WorkerAssignment as WorkAssignment
from app.worker.assignment_schemas import (
    AssignmentBulkStatusUpdate,
    AssignmentCreate,
    AssignmentUpdate,
    AssignmentWithWorker,
)
from app.zeitarbeit.schemas import ZeitarbeitStats
from app.zeitarbeit.service import get_zeitarbeit_stats

router = APIRouter()


def _with_worker_info(assignment: WorkAssignment, users_map: dict[str, User]) -> dict[str, object]:
    u = users_map.get(str(assignment.worker_id))
    shift = None
    if assignment.shift_start and assignment.shift_end:
        shift = (
            f"{assignment.shift_start.strftime('%H:%M')} – {assignment.shift_end.strftime('%H:%M')}"
        )
    return {
        **{c.key: getattr(assignment, c.key) for c in assignment.__table__.columns},
        "worker_name": u.full_name if u else None,
        "worker_email": u.email if u else "",
        # Stable display aliases for consumers that do not need the storage
        # naming (customer_company / role_description / shift_start+end).
        "customer": assignment.customer_company,
        "shift": shift,
        "activity": assignment.role_description,
        "created_at": assignment.created_at.isoformat() if assignment.created_at else "",
        "updated_at": assignment.updated_at.isoformat() if assignment.updated_at else "",
    }


@router.get("", response_model=list[AssignmentWithWorker], summary="Einsatzplanung abrufen")
async def list_assignments(
    user: TenantRecruiterUser,
    db: DBSession,
    month: str | None = Query(None, description="YYYY-MM"),
    worker_id: str | None = Query(None),
    status: str | None = Query(None),
) -> list[dict[str, Any]]:
    stmt = select(WorkAssignment).where(WorkAssignment.tenant_id == user.tenant_id)

    if month:
        try:
            y, m = month.split("-")
            first = date(int(y), int(m), 1)
            last = date(int(y) + 1, 1, 1) if int(m) == 12 else date(int(y), int(m) + 1, 1)
            stmt = stmt.where(
                WorkAssignment.start_date < last,
                WorkAssignment.end_date >= first,
            )
        except (ValueError, IndexError):
            raise HTTPException(status_code=422, detail="month must be YYYY-MM") from None

    if worker_id:
        stmt = stmt.where(WorkAssignment.worker_id == worker_id)

    if status:
        if status not in ASSIGNMENT_STATUSES:
            raise HTTPException(
                status_code=422, detail=f"status must be one of {ASSIGNMENT_STATUSES}"
            )
        stmt = stmt.where(WorkAssignment.status == status)

    stmt = stmt.order_by(WorkAssignment.start_date)
    rows = await db.execute(stmt)
    assignments = list(rows.scalars().all())

    if not assignments:
        return []

    # Enrich with worker names in one query
    worker_ids = list({str(a.worker_id) for a in assignments})
    u_rows = await db.execute(select(User).where(User.id.in_(worker_ids)))
    users_map = {str(u.id): u for u in u_rows.scalars()}

    return [_with_worker_info(a, users_map) for a in assignments]


@router.get("/stats", response_model=ZeitarbeitStats, summary="Einsatzplanung-Statistiken")
async def assignment_stats(user: TenantRecruiterUser, db: DBSession) -> ZeitarbeitStats:
    """Keep the legacy stats URL available after claiming the assignments root."""
    return await get_zeitarbeit_stats(db, user.id)


@router.post("", response_model=AssignmentWithWorker, status_code=201)
async def create_assignment(
    body: AssignmentCreate,
    user: TenantRecruiterUser,
    db: DBSession,
) -> dict[str, Any]:
    # Verify worker belongs to this tenant
    w_row = await db.execute(
        select(User).where(User.id == body.worker_id, User.tenant_id == user.tenant_id)
    )
    worker = w_row.scalar_one_or_none()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker nicht gefunden")

    if body.status not in ASSIGNMENT_STATUSES:
        raise HTTPException(status_code=422, detail=f"Ungültiger Status: {body.status}")

    assignment = WorkAssignment(
        worker_id=body.worker_id,
        tenant_id=user.tenant_id,
        created_by=user.id,
        start_date=body.start_date,
        end_date=body.end_date,
        shift_start=body.shift_start,
        shift_end=body.shift_end,
        customer_company=body.customer_company,
        location=body.location,
        role_description=body.role_description,
        notes=body.notes,
        status=body.status,
    )
    db.add(assignment)
    await db.flush()
    await db.refresh(assignment)
    await db.commit()

    return _with_worker_info(assignment, {str(worker.id): worker})


@router.get("/{assignment_id}", response_model=AssignmentWithWorker)
async def get_assignment(
    assignment_id: str,
    user: TenantRecruiterUser,
    db: DBSession,
) -> dict[str, Any]:
    row = await db.execute(
        select(WorkAssignment).where(
            WorkAssignment.id == assignment_id,
            WorkAssignment.tenant_id == user.tenant_id,
        )
    )
    assignment = row.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Einsatz nicht gefunden")

    w_row = await db.execute(select(User).where(User.id == assignment.worker_id))
    worker = w_row.scalar_one_or_none()
    return _with_worker_info(assignment, {str(assignment.worker_id): worker} if worker else {})


@router.patch("/{assignment_id}", response_model=AssignmentWithWorker)
async def update_assignment(
    assignment_id: str,
    body: AssignmentUpdate,
    user: TenantRecruiterUser,
    db: DBSession,
) -> dict[str, Any]:
    row = await db.execute(
        select(WorkAssignment).where(
            WorkAssignment.id == assignment_id,
            WorkAssignment.tenant_id == user.tenant_id,
        )
    )
    assignment = row.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Einsatz nicht gefunden")

    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in ASSIGNMENT_STATUSES:
        raise HTTPException(status_code=422, detail=f"Ungültiger Status: {data['status']}")

    start = data.get("start_date", assignment.start_date)
    end = data.get("end_date", assignment.end_date)
    if start is None or end is None or end < start:
        raise HTTPException(
            status_code=422, detail="Gültige Einsatzdaten mit Ende ab Start erforderlich."
        )
    for field, value in data.items():
        setattr(assignment, field, value)
    assignment.updated_at = datetime.now()

    await db.commit()
    await db.refresh(assignment)

    w_row = await db.execute(select(User).where(User.id == assignment.worker_id))
    worker = w_row.scalar_one_or_none()
    return _with_worker_info(assignment, {str(assignment.worker_id): worker} if worker else {})


@router.delete("/{assignment_id}", status_code=204)
async def delete_assignment(
    assignment_id: str,
    user: TenantRecruiterUser,
    db: DBSession,
) -> None:
    row = await db.execute(
        select(WorkAssignment).where(
            WorkAssignment.id == assignment_id,
            WorkAssignment.tenant_id == user.tenant_id,
        )
    )
    assignment = row.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Einsatz nicht gefunden")
    await db.delete(assignment)
    await db.commit()


@router.post("/bulk-status", response_model=dict)
async def bulk_update_status(
    body: AssignmentBulkStatusUpdate,
    user: TenantRecruiterUser,
    db: DBSession,
) -> dict[str, Any]:
    if body.status not in ASSIGNMENT_STATUSES:
        raise HTTPException(status_code=422, detail=f"Ungültiger Status: {body.status}")

    ids = [str(i) for i in body.assignment_ids]
    rows = await db.execute(
        select(WorkAssignment).where(
            WorkAssignment.id.in_(ids),
            WorkAssignment.tenant_id == user.tenant_id,
        )
    )
    assignments = list(rows.scalars().all())

    now = datetime.now()
    for a in assignments:
        a.status = body.status
        a.updated_at = now

    await db.commit()
    return {"affected": len(assignments), "status": body.status}
