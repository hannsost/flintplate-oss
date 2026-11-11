"""Worker-facing absence endpoints – /worker/absences (Sprint 4.6)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import extract, select

from app.absences.models import ABSENCE_STATUSES, Absence, calc_working_days
from app.absences.schemas import ABSENCE_TYPE_LABELS, AbsenceCreate, AbsenceRead, AbsenceSummary
from app.dependencies import DBSession, WorkerUser

router = APIRouter()


async def _to_read(absence: Absence, db: DBSession) -> AbsenceRead:
    from app.users.models import User

    worker_row = await db.execute(select(User).where(User.id == absence.worker_id))
    worker = worker_row.scalar_one_or_none()

    reviewer_name = None
    if absence.reviewed_by:
        r_row = await db.execute(select(User).where(User.id == absence.reviewed_by))
        r = r_row.scalar_one_or_none()
        reviewer_name = r.full_name or r.email if r else None

    return AbsenceRead(
        id=absence.id,
        worker_id=absence.worker_id,
        worker_name=worker.full_name if worker else None,
        worker_email=worker.email if worker else "",
        tenant_id=absence.tenant_id,
        absence_type=absence.absence_type,
        absence_type_label=ABSENCE_TYPE_LABELS.get(absence.absence_type, absence.absence_type),
        start_date=absence.start_date,
        end_date=absence.end_date,
        working_days=absence.working_days,
        worker_note=absence.worker_note,
        status=absence.status,
        reviewed_by=absence.reviewed_by,
        reviewed_by_name=reviewer_name,
        reviewed_at=absence.reviewed_at,
        reviewer_note=absence.reviewer_note,
        certificate_uploaded=absence.certificate_uploaded,
        created_at=absence.created_at,
        updated_at=absence.updated_at,
    )


@router.get("", response_model=list[AbsenceRead])
async def list_my_absences(
    user: WorkerUser,
    db: DBSession,
    year: int | None = Query(None),
    status: str | None = Query(None),
) -> list[AbsenceRead]:
    from app.worker.models import WorkerSettings

    ws_row = await db.execute(select(WorkerSettings).where(WorkerSettings.user_id == user.id))
    ws = ws_row.scalar_one_or_none()
    if ws and not ws.active_modules.get("absences", True):
        raise HTTPException(status_code=403, detail="Abwesenheiten-Modul nicht aktiviert")

    stmt = select(Absence).where(Absence.worker_id == user.id)
    if year:
        stmt = stmt.where(extract("year", Absence.start_date) == year)
    if status:
        if status not in ABSENCE_STATUSES:
            raise HTTPException(status_code=422, detail=f"status must be one of {ABSENCE_STATUSES}")
        stmt = stmt.where(Absence.status == status)

    stmt = stmt.order_by(Absence.start_date.desc())
    rows = await db.execute(stmt)
    absences = list(rows.scalars().all())
    return [await _to_read(a, db) for a in absences]


@router.post("", response_model=AbsenceRead, status_code=201)
async def request_absence(body: AbsenceCreate, user: WorkerUser, db: DBSession) -> AbsenceRead:
    from app.worker.models import WorkerSettings

    ws_row = await db.execute(select(WorkerSettings).where(WorkerSettings.user_id == user.id))
    ws = ws_row.scalar_one_or_none()
    if ws and not ws.active_modules.get("absences", True):
        raise HTTPException(status_code=403, detail="Abwesenheiten-Modul nicht aktiviert")

    working_days = calc_working_days(body.start_date, body.end_date)
    absence = Absence(
        worker_id=user.id,
        tenant_id=ws.tenant_id if ws else user.tenant_id,
        absence_type=body.absence_type,
        start_date=body.start_date,
        end_date=body.end_date,
        working_days=working_days,
        worker_note=body.worker_note,
        status="pending",
    )
    db.add(absence)
    await db.flush()
    await db.refresh(absence)
    await db.commit()
    return await _to_read(absence, db)


@router.get("/summary", response_model=AbsenceSummary)
async def get_summary(
    user: WorkerUser,
    db: DBSession,
    year: int | None = Query(None),
) -> AbsenceSummary:
    from datetime import date as date_type

    y = year or date_type.today().year
    rows = await db.execute(
        select(Absence).where(
            Absence.worker_id == user.id,
            extract("year", Absence.start_date) == y,
        )
    )
    absences = list(rows.scalars().all())

    vacation_approved = sum(
        (a.working_days or 0)
        for a in absences
        if a.absence_type == "vacation" and a.status == "approved"
    )
    vacation_pending = sum(
        (a.working_days or 0)
        for a in absences
        if a.absence_type == "vacation" and a.status == "pending"
    )
    sick_approved = sum(
        (a.working_days or 0)
        for a in absences
        if a.absence_type == "sick" and a.status == "approved"
    )
    total = sum((a.working_days or 0) for a in absences if a.status == "approved")

    return AbsenceSummary(
        year=y,
        vacation_days_approved=vacation_approved,
        vacation_days_pending=vacation_pending,
        sick_days_approved=sick_approved,
        total_approved=total,
    )


@router.get("/{absence_id}", response_model=AbsenceRead)
async def get_absence(absence_id: str, user: WorkerUser, db: DBSession) -> AbsenceRead:
    row = await db.execute(
        select(Absence).where(Absence.id == absence_id, Absence.worker_id == user.id)
    )
    absence = row.scalar_one_or_none()
    if not absence:
        raise HTTPException(status_code=404, detail="Abwesenheit nicht gefunden")
    return await _to_read(absence, db)


@router.delete("/{absence_id}", status_code=204)
async def cancel_absence(absence_id: str, user: WorkerUser, db: DBSession) -> None:
    row = await db.execute(
        select(Absence).where(Absence.id == absence_id, Absence.worker_id == user.id)
    )
    absence = row.scalar_one_or_none()
    if not absence:
        raise HTTPException(status_code=404, detail="Abwesenheit nicht gefunden")
    if absence.status == "approved":
        raise HTTPException(
            status_code=409,
            detail="Genehmigte Abwesenheiten können nicht storniert werden. Wende dich an HR.",
        )
    absence.status = "cancelled"
    absence.updated_at = datetime.now()
    await db.commit()
