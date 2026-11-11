"""Worker-facing time tracking endpoints — /worker/time/*"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, func, select

from app.dependencies import DBSession, WorkerUser
from app.worker.models import WorkerSettings
from app.worker.time_models import TimeEntry, TimeEntryCorrection
from app.worker.time_schemas import (
    CorrectionCreate,
    CorrectionRead,
    TimeEntryCreate,
    TimeEntryRead,
    TimeEntrySummary,
    TimeEntryUpdate,
)

router = APIRouter()


# ── helpers ───────────────────────────────────────────────────────────────────


def _to_read(entry: TimeEntry) -> TimeEntryRead:
    return TimeEntryRead(
        **{c: getattr(entry, c) for c in TimeEntryRead.model_fields if hasattr(entry, c)},
    )


async def _own_entry_or_404(
    db: DBSession,
    entry_id: uuid.UUID,
    worker_id: uuid.UUID,
) -> TimeEntry:
    row = await db.execute(
        select(TimeEntry).where(TimeEntry.id == entry_id, TimeEntry.worker_id == worker_id)
    )
    entry = row.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Zeiteintrag nicht gefunden.")
    return entry


def validate_interval(clock_in: datetime, clock_out: datetime | None, break_minutes: int) -> None:
    if clock_out is None:
        return
    minutes = (clock_out - clock_in).total_seconds() / 60
    if minutes < 0:
        raise HTTPException(status_code=422, detail="Ausstempeln muss nach dem Einstempeln liegen.")
    if break_minutes > minutes:
        raise HTTPException(
            status_code=422, detail="Die Pause darf die Anwesenheitszeit nicht überschreiten."
        )


# ── list / summary ────────────────────────────────────────────────────────────


@router.get("", response_model=list[TimeEntryRead])
async def list_entries(
    user: WorkerUser,
    db: DBSession,
    month: str | None = Query(None, pattern=r"^[1-9]\d{3}-(0[1-9]|1[0-2])$", description="YYYY-MM"),
    status: str | None = Query(None),
) -> list[TimeEntryRead]:
    """Return this worker's time entries, optionally filtered by month and status."""
    filters = [TimeEntry.worker_id == user.id]
    if month:
        year, m = int(month[:4]), int(month[5:])
        start = date(year, m, 1)
        end = date(year + (m // 12), m % 12 + 1, 1) if m < 12 else date(year + 1, 1, 1)
        filters.append(TimeEntry.entry_date >= start)
        filters.append(TimeEntry.entry_date < end)
    if status:
        filters.append(TimeEntry.status == status)

    rows = await db.execute(
        select(TimeEntry).where(and_(*filters)).order_by(TimeEntry.entry_date.desc())
    )
    return [_to_read(e) for e in rows.scalars()]


@router.get("/summary", response_model=TimeEntrySummary)
async def get_summary(
    user: WorkerUser,
    db: DBSession,
    month: str = Query(..., pattern=r"^[1-9]\d{3}-(0[1-9]|1[0-2])$"),
) -> TimeEntrySummary:
    year, m = int(month[:4]), int(month[5:])
    start = date(year, m, 1)
    end = date(year + (m // 12), m % 12 + 1, 1) if m < 12 else date(year + 1, 1, 1)

    rows = await db.execute(
        select(TimeEntry).where(
            TimeEntry.worker_id == user.id,
            TimeEntry.entry_date >= start,
            TimeEntry.entry_date < end,
        )
    )
    entries = rows.scalars().all()

    def _net(e: TimeEntry) -> int:
        return e.net_minutes or 0

    pending_corr = await db.execute(
        select(func.count())
        .select_from(TimeEntryCorrection)
        .where(
            TimeEntryCorrection.status == "pending",
            TimeEntryCorrection.entry_id.in_([e.id for e in entries]),
        )
    )

    return TimeEntrySummary(
        period=month,
        total_entries=len(entries),
        approved_minutes=sum(_net(e) for e in entries if e.status == "approved"),
        submitted_minutes=sum(_net(e) for e in entries if e.status == "submitted"),
        draft_minutes=sum(_net(e) for e in entries if e.status == "draft"),
        pending_corrections=pending_corr.scalar_one() or 0,
    )


# ── clock-in ──────────────────────────────────────────────────────────────────


@router.post("", response_model=TimeEntryRead, status_code=201)
async def clock_in(
    user: WorkerUser,
    db: DBSession,
    data: TimeEntryCreate,
) -> TimeEntryRead:
    """Create a new time entry (clock-in)."""
    # Check worker is active
    ws = await db.execute(select(WorkerSettings).where(WorkerSettings.user_id == user.id))
    settings = ws.scalar_one_or_none()
    if not settings or not settings.is_active:
        raise HTTPException(status_code=403, detail="Worker-Zugang inaktiv.")
    if not (settings.active_modules or {}).get("timetracking", True):
        raise HTTPException(status_code=403, detail="Zeiterfassung nicht freigeschaltet.")

    from app.users.models import User

    # Serialize concurrent clock-ins for the same person before checking drafts.
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    open_entry = await db.scalar(
        select(TimeEntry.id).where(
            TimeEntry.worker_id == user.id,
            TimeEntry.status == "draft",
            TimeEntry.clock_out.is_(None),
        )
    )
    if open_entry is not None:
        raise HTTPException(status_code=409, detail="Du bist bereits eingestempelt.")
    if data.assignment_id:
        from app.zeitarbeit.models import WorkAssignment

        assignment = await db.get(WorkAssignment, data.assignment_id)
        if assignment is None or assignment.tenant_id != user.tenant_id:
            raise HTTPException(status_code=404, detail="Einsatz nicht gefunden.")

    now = datetime.now(UTC).replace(tzinfo=None)
    entry = TimeEntry(
        worker_id=user.id,
        tenant_id=settings.tenant_id,
        assignment_id=data.assignment_id,
        entry_date=data.entry_date or now.date(),
        clock_in=data.clock_in or now,
        break_minutes=0,
        status="draft",
        location_note=data.location_note,
        project_code=data.project_code,
        cost_center=data.cost_center,
        gps_lat=data.gps_lat,
        gps_lon=data.gps_lon,
        worker_note=data.worker_note,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return _to_read(entry)


# ── update (clock-out / edit) ─────────────────────────────────────────────────


@router.patch("/{entry_id}", response_model=TimeEntryRead)
async def update_entry(
    entry_id: uuid.UUID,
    data: TimeEntryUpdate,
    user: WorkerUser,
    db: DBSession,
) -> TimeEntryRead:
    """Clock out or update an open draft entry."""
    entry = await _own_entry_or_404(db, entry_id, user.id)
    if entry.status not in ("draft",):
        raise HTTPException(
            status_code=409,
            detail="Nur Entwürfe können direkt bearbeitet werden. Bitte Korrekturanfrage stellen.",
        )
    validate_interval(
        entry.clock_in,
        data.clock_out if "clock_out" in data.model_fields_set else entry.clock_out,
        data.break_minutes if data.break_minutes is not None else entry.break_minutes,
    )
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    entry.updated_at = datetime.now(UTC).replace(tzinfo=None)
    await db.commit()
    await db.refresh(entry)
    return _to_read(entry)


# ── submit ────────────────────────────────────────────────────────────────────


@router.post("/{entry_id}/submit", response_model=TimeEntryRead)
async def submit_entry(
    entry_id: uuid.UUID,
    user: WorkerUser,
    db: DBSession,
) -> TimeEntryRead:
    """Submit a draft entry for manager approval."""
    entry = await _own_entry_or_404(db, entry_id, user.id)
    if entry.status != "draft":
        raise HTTPException(
            status_code=409, detail=f"Eintrag hat Status '{entry.status}', nicht 'draft'."
        )
    if entry.clock_out is None:
        raise HTTPException(status_code=422, detail="Bitte zuerst ausstempeln (clock_out fehlt).")
    entry.status = "submitted"
    entry.updated_at = datetime.now(UTC).replace(tzinfo=None)
    await db.commit()
    await db.refresh(entry)
    return _to_read(entry)


# ── correction request ────────────────────────────────────────────────────────


@router.post("/{entry_id}/correction", response_model=CorrectionRead, status_code=201)
async def request_correction(
    entry_id: uuid.UUID,
    data: CorrectionCreate,
    user: WorkerUser,
    db: DBSession,
) -> CorrectionRead:
    """Request a correction on a submitted/approved entry."""
    entry = await _own_entry_or_404(db, entry_id, user.id)
    if entry.status not in ("submitted", "approved", "rejected"):
        raise HTTPException(
            status_code=409, detail="Korrekturen nur für eingereichte oder freigegebene Einträge."
        )

    old_values = {
        "clock_in": entry.clock_in.isoformat(),
        "clock_out": entry.clock_out.isoformat() if entry.clock_out else None,
        "break_minutes": entry.break_minutes,
    }
    new_values: dict[str, Any] = {}
    if data.new_clock_in is not None:
        new_values["clock_in"] = data.new_clock_in.isoformat()
    if data.new_clock_out is not None:
        new_values["clock_out"] = data.new_clock_out.isoformat()
    if data.new_break_minutes is not None:
        new_values["break_minutes"] = data.new_break_minutes

    if not new_values:
        raise HTTPException(status_code=422, detail="Mindestens ein Feld muss korrigiert werden.")

    validate_interval(
        data.new_clock_in or entry.clock_in,
        data.new_clock_out or entry.clock_out,
        data.new_break_minutes if data.new_break_minutes is not None else entry.break_minutes,
    )
    correction = TimeEntryCorrection(
        entry_id=entry_id,
        requested_by=user.id,
        old_values=old_values,
        new_values=new_values,
        reason=data.reason,
        status="pending",
    )
    entry.status = "correction_requested"
    entry.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.add(correction)
    await db.commit()
    await db.refresh(correction)
    return CorrectionRead.model_validate(correction)


# ── single entry ──────────────────────────────────────────────────────────────


@router.get("/{entry_id}", response_model=TimeEntryRead)
async def get_entry(
    entry_id: uuid.UUID,
    user: WorkerUser,
    db: DBSession,
) -> TimeEntryRead:
    entry = await _own_entry_or_404(db, entry_id, user.id)
    return _to_read(entry)
