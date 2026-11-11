"""HR absence management endpoints – /zeitarbeit/absences (Sprint 4.6)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import extract, select

from app.absences.models import ABSENCE_STATUSES, ABSENCE_TYPES, Absence
from app.absences.schemas import ABSENCE_TYPE_LABELS, AbsenceRead, AbsenceReview
from app.dependencies import DBSession, TenantRecruiterUser

router = APIRouter()


async def _to_read(absence: Absence, db: DBSession) -> AbsenceRead:
    from app.users.models import User

    user_ids = {str(absence.worker_id)}
    if absence.reviewed_by:
        user_ids.add(str(absence.reviewed_by))
    u_rows = await db.execute(select(User).where(User.id.in_(user_ids)))
    users = {str(u.id): u for u in u_rows.scalars()}

    worker = users.get(str(absence.worker_id))
    reviewer = users.get(str(absence.reviewed_by)) if absence.reviewed_by else None

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
        reviewed_by_name=(reviewer.full_name or reviewer.email) if reviewer else None,
        reviewed_at=absence.reviewed_at,
        reviewer_note=absence.reviewer_note,
        certificate_uploaded=absence.certificate_uploaded,
        created_at=absence.created_at,
        updated_at=absence.updated_at,
    )


@router.get("", response_model=list[AbsenceRead])
async def list_absences(
    user: TenantRecruiterUser,
    db: DBSession,
    status: str | None = Query(None),
    worker_id: str | None = Query(None),
    year: int | None = Query(None),
    absence_type: str | None = Query(None),
) -> list[AbsenceRead]:
    stmt = select(Absence).where(Absence.tenant_id == user.tenant_id)

    if status:
        if status not in ABSENCE_STATUSES:
            raise HTTPException(status_code=422, detail=f"status must be one of {ABSENCE_STATUSES}")
        stmt = stmt.where(Absence.status == status)
    if worker_id:
        stmt = stmt.where(Absence.worker_id == worker_id)
    if year:
        stmt = stmt.where(extract("year", Absence.start_date) == year)
    if absence_type:
        if absence_type not in ABSENCE_TYPES:
            raise HTTPException(status_code=422, detail=f"type must be one of {ABSENCE_TYPES}")
        stmt = stmt.where(Absence.absence_type == absence_type)

    stmt = stmt.order_by(Absence.created_at.desc())
    rows = await db.execute(stmt)
    absences = list(rows.scalars().all())
    return [await _to_read(a, db) for a in absences]


@router.get("/{absence_id}", response_model=AbsenceRead)
async def get_absence(absence_id: str, user: TenantRecruiterUser, db: DBSession) -> AbsenceRead:
    row = await db.execute(
        select(Absence).where(Absence.id == absence_id, Absence.tenant_id == user.tenant_id)
    )
    absence = row.scalar_one_or_none()
    if not absence:
        raise HTTPException(status_code=404, detail="Abwesenheit nicht gefunden")
    return await _to_read(absence, db)


@router.post("/{absence_id}/review", response_model=AbsenceRead)
async def review_absence(
    absence_id: str, body: AbsenceReview, user: TenantRecruiterUser, db: DBSession
) -> AbsenceRead:
    row = await db.execute(
        select(Absence).where(Absence.id == absence_id, Absence.tenant_id == user.tenant_id)
    )
    absence = row.scalar_one_or_none()
    if not absence:
        raise HTTPException(status_code=404, detail="Abwesenheit nicht gefunden")
    if absence.status not in ("pending",):
        raise HTTPException(status_code=409, detail=f"Abwesenheit ist bereits '{absence.status}'")

    now = datetime.now()
    absence.status = "approved" if body.action == "approve" else "rejected"
    absence.reviewed_by = user.id
    absence.reviewed_at = now
    absence.reviewer_note = body.reviewer_note
    absence.updated_at = now
    await db.commit()
    await db.refresh(absence)
    return await _to_read(absence, db)


@router.delete("/{absence_id}", status_code=204)
async def hr_cancel_absence(absence_id: str, user: TenantRecruiterUser, db: DBSession) -> None:
    """HR can cancel any absence (e.g. retroactive correction)."""
    row = await db.execute(
        select(Absence).where(Absence.id == absence_id, Absence.tenant_id == user.tenant_id)
    )
    absence = row.scalar_one_or_none()
    if not absence:
        raise HTTPException(status_code=404, detail="Abwesenheit nicht gefunden")
    absence.status = "cancelled"
    absence.updated_at = datetime.now()
    await db.commit()
