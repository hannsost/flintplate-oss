"""Interview schedule endpoints – Sprint 1.5.

Mounted at /applications/{application_id}/interview
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.applications.models import Application
from app.database import get_db
from app.interviews.models import InterviewSchedule, InterviewScorecard
from app.interviews.schemas import (
    InterviewScheduleCreate,
    InterviewScheduleRead,
    InterviewScheduleUpdate,
)
from app.interviews.service import (
    get_interview,
    propose_interview,
    update_interview_status,
)
from app.jobs.models import JobPosting
from app.pipeline.access import require_application
from app.security import get_current_user
from app.users.models import User

router = APIRouter()

_VALID_STATUSES = {"confirmed", "declined", "cancelled"}


async def _load_application(db: AsyncSession, application_id: uuid.UUID) -> Application:
    result = await db.execute(select(Application).where(Application.id == application_id))
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Bewerbung nicht gefunden.")
    return app


async def _require_hr_application(
    db: AsyncSession, application_id: uuid.UUID, user: User
) -> Application:
    if user.role not in {"recruiter", "admin"}:
        raise HTTPException(status_code=403, detail="Nur für Recruiter.")
    return await require_application(db, application_id, user)


async def _require_participant(
    db: AsyncSession, application_id: uuid.UUID, user: User
) -> Application:
    app = await _load_application(db, application_id)
    if app.user_id == user.id:
        return app
    return await _require_hr_application(db, application_id, user)


@router.post(
    "/{application_id}/interview",
    response_model=InterviewScheduleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Interview-Termin vorschlagen (Recruiter)",
)
async def propose(
    application_id: uuid.UUID,
    data: InterviewScheduleCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InterviewSchedule:
    app = await _require_hr_application(db, application_id, current_user)

    # Resolve job title for the notification message
    job_title = "Stelle"
    if app.job_id:
        job_result = await db.execute(select(JobPosting).where(JobPosting.id == app.job_id))
        job = job_result.scalar_one_or_none()
        if job:
            job_title = job.title

    schedule = await propose_interview(
        db=db,
        application_id=application_id,
        proposed_by=current_user.id,
        data=data,
        candidate_user_id=app.user_id,
        job_title=job_title,
        tenant_id=current_user.tenant_id,
    )
    await db.commit()
    return schedule


@router.get(
    "/{application_id}/interview",
    response_model=InterviewScheduleRead | None,
    summary="Aktuellen Interview-Termin abrufen",
)
async def get_current(
    application_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InterviewSchedule | None:
    await _require_participant(db, application_id, current_user)

    return await get_interview(db, application_id)


@router.patch(
    "/{application_id}/interview",
    response_model=InterviewScheduleRead,
    summary="Interview bestätigen / ablehnen / absagen",
)
async def update_status(
    application_id: uuid.UUID,
    data: InterviewScheduleUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InterviewSchedule:
    if data.status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Ungültiger Status. Erlaubt: {', '.join(_VALID_STATUSES)}",
        )

    app = await _require_participant(db, application_id, current_user)

    schedule = await get_interview(db, application_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Kein aktiver Interview-Termin gefunden.")

    # Permission checks
    if data.status in {"confirmed", "declined"} and app.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Nur der Kandidat kann bestätigen/ablehnen.")
    if data.status == "cancelled":
        await _require_hr_application(db, application_id, current_user)

    # Resolve recruiter user_id (job owner) for notifications
    recruiter_id: uuid.UUID | None = None
    if app.job_id:
        job_result = await db.execute(select(JobPosting).where(JobPosting.id == app.job_id))
        job = job_result.scalar_one_or_none()
        if job:
            recruiter_id = job.owner_id

    updated = await update_interview_status(
        db=db,
        schedule=schedule,
        new_status=data.status,
        notes=data.notes,
        candidate_user_id=app.user_id,
        recruiter_user_id=recruiter_id,
        candidate_name=current_user.full_name,
        job_title=app.position,
    )
    await db.commit()
    return updated


# ── Scorecard ──────────────────────────────────────────────────────────────────


class ScorecardUpsert(BaseModel):
    overall_rating: int | None = Field(None, ge=1, le=5)
    technical_rating: int | None = Field(None, ge=1, le=5)
    communication_rating: int | None = Field(None, ge=1, le=5)
    motivation_rating: int | None = Field(None, ge=1, le=5)
    notes: str | None = None
    recommendation: str | None = None  # hire | no_hire | maybe


class ScorecardRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    application_id: uuid.UUID
    recruiter_id: uuid.UUID | None
    overall_rating: int | None
    technical_rating: int | None
    communication_rating: int | None
    motivation_rating: int | None
    notes: str | None
    recommendation: str | None
    created_at: str
    updated_at: str


@router.put(
    "/{application_id}/scorecard",
    response_model=ScorecardRead,
    summary="Interview-Bewertung speichern (erstellen oder aktualisieren)",
)
async def upsert_scorecard(
    application_id: uuid.UUID,
    data: ScorecardUpsert,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ScorecardRead:
    await _require_hr_application(db, application_id, current_user)

    # Upsert scorecard
    result = await db.execute(
        select(InterviewScorecard).where(InterviewScorecard.application_id == application_id)
    )
    scorecard = result.scalar_one_or_none()

    if scorecard:
        for field, val in data.model_dump(exclude_unset=True).items():
            setattr(scorecard, field, val)
    else:
        scorecard = InterviewScorecard(
            application_id=application_id,
            recruiter_id=current_user.id,
            **data.model_dump(),
        )
        db.add(scorecard)

    await db.commit()
    await db.refresh(scorecard)

    return ScorecardRead(
        id=scorecard.id,
        application_id=scorecard.application_id,
        recruiter_id=scorecard.recruiter_id,
        overall_rating=scorecard.overall_rating,
        technical_rating=scorecard.technical_rating,
        communication_rating=scorecard.communication_rating,
        motivation_rating=scorecard.motivation_rating,
        notes=scorecard.notes,
        recommendation=scorecard.recommendation,
        created_at=scorecard.created_at.isoformat(),
        updated_at=scorecard.updated_at.isoformat(),
    )


@router.get(
    "/{application_id}/scorecard",
    response_model=ScorecardRead | None,
    summary="Interview-Bewertung abrufen",
)
async def get_scorecard(
    application_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ScorecardRead | None:
    await _require_participant(db, application_id, current_user)

    result = await db.execute(
        select(InterviewScorecard).where(InterviewScorecard.application_id == application_id)
    )
    sc = result.scalar_one_or_none()
    if not sc:
        return None

    return ScorecardRead(
        id=sc.id,
        application_id=sc.application_id,
        recruiter_id=sc.recruiter_id,
        overall_rating=sc.overall_rating,
        technical_rating=sc.technical_rating,
        communication_rating=sc.communication_rating,
        motivation_rating=sc.motivation_rating,
        notes=sc.notes,
        recommendation=sc.recommendation,
        created_at=sc.created_at.isoformat(),
        updated_at=sc.updated_at.isoformat(),
    )


# ── Candidate: list my interview schedules ─────────────────────────────────────


class CandidateInterviewOut(PydanticBaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    job_title: str
    scheduled_at: str
    status: str
    meeting_url: str | None


@router.get(
    "/my-interviews",
    response_model=list[CandidateInterviewOut],
    summary="List all interview schedules for the current user (candidate)",
)
async def list_my_interviews(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[CandidateInterviewOut]:
    AppAlias = aliased(Application)
    result = await db.execute(
        select(InterviewSchedule, JobPosting.title)
        .join(AppAlias, InterviewSchedule.application_id == AppAlias.id)
        .outerjoin(JobPosting, AppAlias.job_id == JobPosting.id)
        .where(AppAlias.user_id == current_user.id)
        .order_by(InterviewSchedule.scheduled_at.desc())
    )
    rows = result.all()
    return [
        CandidateInterviewOut(
            id=iv.id,
            application_id=iv.application_id,
            job_title=title or "Stelle",
            scheduled_at=iv.scheduled_at.isoformat(),
            status=iv.status,
            meeting_url=iv.meeting_url,
        )
        for iv, title in rows
    ]
