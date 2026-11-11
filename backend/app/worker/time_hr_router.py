"""HR/Disponent endpoints for time-entry approval — /zeitarbeit/time-entries/*"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, select

from app.dependencies import DBSession, TenantRecruiterUser
from app.users.models import User
from app.worker.time_models import TimeEntry, TimeEntryCorrection
from app.worker.time_schemas import (
    ApprovalAction,
    BulkApprovalRequest,
    CorrectionRead,
    PendingEntryRead,
    TimeEntryRead,
)

router = APIRouter()


# ── helpers ───────────────────────────────────────────────────────────────────


def _to_pending(entry: TimeEntry, worker: User) -> PendingEntryRead:
    return PendingEntryRead(
        **{c: getattr(entry, c) for c in TimeEntryRead.model_fields if hasattr(entry, c)},
        worker_name=worker.full_name,
        worker_email=worker.email,
    )


# ── pending queue ─────────────────────────────────────────────────────────────


@router.get("/pending", response_model=list[PendingEntryRead])
async def list_pending(
    user: TenantRecruiterUser,
    db: DBSession,
    worker_id: uuid.UUID | None = Query(None),
) -> list[PendingEntryRead]:
    """All submitted entries awaiting approval for this tenant."""
    filters = [
        TimeEntry.tenant_id == user.tenant_id,
        TimeEntry.status.in_(("submitted", "correction_requested")),
    ]
    if worker_id:
        filters.append(TimeEntry.worker_id == worker_id)

    rows = await db.execute(
        select(TimeEntry).where(and_(*filters)).order_by(TimeEntry.entry_date.asc())
    )
    entries = rows.scalars().all()
    if not entries:
        return []

    worker_ids = {e.worker_id for e in entries}
    w_rows = await db.execute(select(User).where(User.id.in_(worker_ids)))
    workers = {u.id: u for u in w_rows.scalars()}

    return [_to_pending(e, workers[e.worker_id]) for e in entries if e.worker_id in workers]


@router.get("/all", response_model=list[PendingEntryRead])
async def list_all(
    user: TenantRecruiterUser,
    db: DBSession,
    worker_id: uuid.UUID | None = Query(None),
    month: str | None = Query(None, pattern=r"^[1-9]\d{3}-(0[1-9]|1[0-2])$"),
    status: str | None = Query(None),
) -> list[PendingEntryRead]:
    """All time entries for this tenant (HR overview)."""
    from datetime import date

    filters = [TimeEntry.tenant_id == user.tenant_id]
    if worker_id:
        filters.append(TimeEntry.worker_id == worker_id)
    if month:
        yr, m = int(month[:4]), int(month[5:])
        start = date(yr, m, 1)
        end = date(yr + (m // 12), m % 12 + 1, 1) if m < 12 else date(yr + 1, 1, 1)
        filters.append(TimeEntry.entry_date >= start)
        filters.append(TimeEntry.entry_date < end)
    if status == "pending":
        # The UI groups submitted entries and correction requests as pending.
        filters.append(TimeEntry.status.in_(("submitted", "correction_requested")))
    elif status:
        filters.append(TimeEntry.status == status)

    rows = await db.execute(
        select(TimeEntry).where(and_(*filters)).order_by(TimeEntry.entry_date.desc())
    )
    entries = rows.scalars().all()
    if not entries:
        return []

    worker_ids = {e.worker_id for e in entries}
    w_rows = await db.execute(select(User).where(User.id.in_(worker_ids)))
    workers = {u.id: u for u in w_rows.scalars()}

    return [_to_pending(e, workers[e.worker_id]) for e in entries if e.worker_id in workers]


async def _apply_decision(
    db: DBSession, entry: TimeEntry, action: str, note: str | None, actor_id: uuid.UUID
) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    if action == "approve":
        entry.status = "approved"
        entry.approved_by = actor_id
        entry.approved_at = now
        entry.rejection_note = None
        # If there's a pending correction, apply it and resolve
        corr_row = await db.execute(
            select(TimeEntryCorrection)
            .where(
                TimeEntryCorrection.entry_id == entry.id,
                TimeEntryCorrection.status == "pending",
            )
            .order_by(TimeEntryCorrection.created_at.desc())
            .limit(1)
        )
        correction = corr_row.scalar_one_or_none()
        if correction:
            nv = correction.new_values
            if "clock_in" in nv:
                entry.clock_in = datetime.fromisoformat(nv["clock_in"])
            if "clock_out" in nv:
                entry.clock_out = datetime.fromisoformat(nv["clock_out"])
            if "break_minutes" in nv:
                entry.break_minutes = nv["break_minutes"]
            correction.status = "approved"
            correction.resolved_by = actor_id
            correction.resolved_at = now
    else:
        entry.status = "rejected"
        entry.rejection_note = note
        # Reject any pending corrections too
        corr_rows = await db.execute(
            select(TimeEntryCorrection).where(
                TimeEntryCorrection.entry_id == entry.id,
                TimeEntryCorrection.status == "pending",
            )
        )
        for c in corr_rows.scalars():
            c.status = "rejected"
            c.resolved_by = actor_id
            c.resolved_at = now

    entry.updated_at = now


# ── single approve / reject ───────────────────────────────────────────────────


@router.post("/{entry_id}/decision", response_model=TimeEntryRead)
async def decide_entry(
    entry_id: uuid.UUID,
    data: ApprovalAction,
    user: TenantRecruiterUser,
    db: DBSession,
) -> TimeEntryRead:
    row = await db.execute(
        select(TimeEntry).where(
            TimeEntry.id == entry_id,
            TimeEntry.tenant_id == user.tenant_id,
        )
    )
    entry = row.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Zeiteintrag nicht gefunden.")
    if entry.status not in ("submitted", "correction_requested"):
        raise HTTPException(
            status_code=409, detail=f"Status '{entry.status}' kann nicht freigegeben werden."
        )
    if data.action == "reject" and not data.note:
        raise HTTPException(status_code=422, detail="Ablehnungsgrund ist erforderlich.")

    await _apply_decision(db, entry, data.action, data.note, user.id)
    await db.commit()
    await db.refresh(entry)
    from app.worker.time_router import _to_read

    return _to_read(entry)


# ── bulk approve ──────────────────────────────────────────────────────────────


@router.post("/bulk-decision", response_model=dict)
async def bulk_decide(
    data: BulkApprovalRequest,
    user: TenantRecruiterUser,
    db: DBSession,
) -> dict[str, Any]:
    rows = await db.execute(
        select(TimeEntry).where(
            TimeEntry.id.in_(data.entry_ids),
            TimeEntry.tenant_id == user.tenant_id,
            TimeEntry.status.in_(("submitted", "correction_requested")),
        )
    )
    entries = rows.scalars().all()
    if not entries:
        raise HTTPException(status_code=404, detail="Keine verarbeitbaren Einträge gefunden.")
    if data.action == "reject" and not data.note:
        raise HTTPException(status_code=422, detail="Ablehnungsgrund erforderlich.")

    for entry in entries:
        await _apply_decision(db, entry, data.action, data.note, user.id)

    await db.commit()
    return {"affected": len(entries), "action": data.action}


# ── corrections list ──────────────────────────────────────────────────────────


@router.get("/corrections/pending", response_model=list[CorrectionRead])
async def list_pending_corrections(
    user: TenantRecruiterUser,
    db: DBSession,
) -> list[CorrectionRead]:
    """Pending correction requests for this tenant."""
    rows = await db.execute(
        select(TimeEntryCorrection)
        .join(TimeEntry, TimeEntry.id == TimeEntryCorrection.entry_id)
        .where(
            TimeEntry.tenant_id == user.tenant_id,
            TimeEntryCorrection.status == "pending",
        )
        .order_by(TimeEntryCorrection.created_at.asc())
    )
    return [CorrectionRead.model_validate(c) for c in rows.scalars()]


# ── CSV export ────────────────────────────────────────────────────────────────


@router.get("/export")
async def export_csv(
    user: TenantRecruiterUser,
    db: DBSession,
    worker_id: uuid.UUID | None = Query(None),
    month: str = Query(..., pattern=r"^[1-9]\d{3}-(0[1-9]|1[0-2])$"),
) -> dict[str, Any]:
    """Return approved entries as JSON rows suitable for CSV export."""
    from datetime import date

    yr, m = int(month[:4]), int(month[5:])
    start = date(yr, m, 1)
    end = date(yr + (m // 12), m % 12 + 1, 1) if m < 12 else date(yr + 1, 1, 1)

    filters = [
        TimeEntry.tenant_id == user.tenant_id,
        TimeEntry.status == "approved",
        TimeEntry.entry_date >= start,
        TimeEntry.entry_date < end,
    ]
    if worker_id:
        filters.append(TimeEntry.worker_id == worker_id)

    rows = await db.execute(
        select(TimeEntry).where(and_(*filters)).order_by(TimeEntry.worker_id, TimeEntry.entry_date)
    )
    entries = rows.scalars().all()

    worker_ids = {e.worker_id for e in entries}
    w_rows = await db.execute(select(User).where(User.id.in_(worker_ids)))
    workers = {u.id: u for u in w_rows.scalars()}

    return {
        "period": month,
        "rows": [
            {
                "worker": workers[e.worker_id].full_name or workers[e.worker_id].email,
                "email": workers[e.worker_id].email,
                "date": str(e.entry_date),
                "clock_in": e.clock_in.isoformat(),
                "clock_out": e.clock_out.isoformat() if e.clock_out else None,
                "break_minutes": e.break_minutes,
                "net_hours": round((e.net_minutes or 0) / 60, 2),
                "location": e.location_note,
                "project": e.project_code,
                "cost_center": e.cost_center,
            }
            for e in entries
            if e.worker_id in workers
        ],
    }
