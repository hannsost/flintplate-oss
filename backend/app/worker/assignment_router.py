"""Worker-facing schedule endpoints – GET /worker/schedule (Sprint 4.3)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.dependencies import DBSession, WorkerUser
from app.worker.assignment_models import WorkerAssignment as WorkAssignment
from app.worker.assignment_schemas import AssignmentRead

router = APIRouter()


@router.get("", response_model=list[AssignmentRead])
async def get_my_schedule(
    user: WorkerUser,
    db: DBSession,
    month: str | None = Query(None, description="YYYY-MM – filter by month"),
    upcoming: bool = Query(False, description="Only assignments from today onwards"),
) -> list[WorkAssignment]:
    """Return the authenticated worker's assignments, optionally filtered."""
    from app.worker.models import WorkerSettings

    # Check module enabled
    ws_row = await db.execute(select(WorkerSettings).where(WorkerSettings.user_id == user.id))
    ws = ws_row.scalar_one_or_none()
    if ws and not ws.active_modules.get("schedule", True):
        raise HTTPException(status_code=403, detail="Einsatzplan-Modul nicht aktiviert")

    stmt = select(WorkAssignment).where(WorkAssignment.worker_id == user.id)

    if month:
        try:
            y, m = month.split("-")
            first = date(int(y), int(m), 1)
            # Last day of month
            last = date(int(y) + 1, 1, 1) if int(m) == 12 else date(int(y), int(m) + 1, 1)
            stmt = stmt.where(
                WorkAssignment.start_date < last,
                WorkAssignment.end_date >= first,
            )
        except (ValueError, IndexError):
            raise HTTPException(status_code=422, detail="month must be YYYY-MM") from None
    elif upcoming:
        stmt = stmt.where(WorkAssignment.end_date >= date.today())

    stmt = stmt.order_by(WorkAssignment.start_date)
    rows = await db.execute(stmt)
    return list(rows.scalars().all())


@router.get("/{assignment_id}", response_model=AssignmentRead)
async def get_assignment(
    assignment_id: str,
    user: WorkerUser,
    db: DBSession,
) -> WorkAssignment:
    row = await db.execute(
        select(WorkAssignment).where(
            WorkAssignment.id == assignment_id,
            WorkAssignment.worker_id == user.id,
        )
    )
    assignment = row.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Einsatz nicht gefunden")
    return assignment
