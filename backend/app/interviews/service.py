"""Interview schedule service – Sprint 1.5."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.interviews.models import InterviewSchedule
from app.interviews.schemas import InterviewScheduleCreate
from app.users.models import User


async def propose_interview(
    db: AsyncSession,
    application_id: uuid.UUID,
    proposed_by: uuid.UUID,
    data: InterviewScheduleCreate,
    candidate_user_id: uuid.UUID,
    job_title: str,
    tenant_id: uuid.UUID | None = None,
) -> InterviewSchedule:
    """Recruiter creates an interview proposal. Notifies candidate via WS + DB."""
    # The booking flow locks the same interviewer before checking availability.
    await db.execute(select(User.id).where(User.id == proposed_by).with_for_update())
    existing = (
        await db.execute(
            select(InterviewSchedule).where(
                InterviewSchedule.proposed_by == proposed_by,
                InterviewSchedule.status.in_(["proposed", "confirmed"]),
                InterviewSchedule.scheduled_at >= data.scheduled_at - timedelta(hours=2),
                InterviewSchedule.scheduled_at < data.scheduled_at + timedelta(minutes=30),
            )
        )
    ).scalars()
    if any(
        item.scheduled_at + timedelta(minutes=item.duration_minutes) > data.scheduled_at
        for item in existing
    ):
        raise HTTPException(409, "Diese Zeit ist bereits durch ein anderes Interview belegt.")
    schedule = InterviewSchedule(
        application_id=application_id,
        tenant_id=tenant_id,
        created_at=datetime.now(UTC),
        proposed_by=proposed_by,
        scheduled_at=data.scheduled_at,
        status="proposed",
        meeting_url=data.meeting_url,
        notes=data.notes,
    )
    db.add(schedule)
    await db.flush()

    # Notify candidate
    from app.notifications.service import create_and_push

    dt_str = data.scheduled_at.strftime("%d.%m.%Y um %H:%M Uhr")
    await create_and_push(
        db=db,
        user_id=candidate_user_id,
        type_="interview.proposed",
        title="Interview-Einladung",
        body=f"Du wurdest zu einem Interview eingeladen: {job_title} – {dt_str}",
        meta={
            "application_id": str(application_id),
            "schedule_id": str(schedule.id),
            "scheduled_at": data.scheduled_at.isoformat(),
        },
    )

    return schedule


async def get_interview(db: AsyncSession, application_id: uuid.UUID) -> InterviewSchedule | None:
    """Get the latest (non-cancelled) interview for an application."""
    result = await db.execute(
        select(InterviewSchedule)
        .where(
            InterviewSchedule.application_id == application_id,
            InterviewSchedule.status.not_in(["cancelled", "declined"]),
        )
        .order_by(InterviewSchedule.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def update_interview_status(
    db: AsyncSession,
    schedule: InterviewSchedule,
    new_status: str,
    notes: str | None,
    candidate_user_id: uuid.UUID,
    recruiter_user_id: uuid.UUID | None,
    candidate_name: str | None,
    job_title: str,
) -> InterviewSchedule:
    """Candidate confirms/declines; recruiter cancels. Notifies the other party."""
    schedule.status = new_status
    if notes:
        schedule.notes = notes
    await db.flush()

    from app.notifications.service import create_and_push

    dt_str = schedule.scheduled_at.strftime("%d.%m.%Y um %H:%M Uhr")

    if new_status == "confirmed" and recruiter_user_id:
        await create_and_push(
            db=db,
            user_id=recruiter_user_id,
            type_="interview.confirmed",
            title="Interview bestätigt",
            body=f"{candidate_name or 'Kandidat'} hat den Termin am {dt_str} bestätigt.",
            meta={"schedule_id": str(schedule.id), "application_id": str(schedule.application_id)},
        )
    elif new_status == "declined" and recruiter_user_id:
        await create_and_push(
            db=db,
            user_id=recruiter_user_id,
            type_="interview.declined",
            title="Interview abgelehnt",
            body=f"{candidate_name or 'Kandidat'} hat den Termin am {dt_str} abgelehnt.",
            meta={"schedule_id": str(schedule.id), "application_id": str(schedule.application_id)},
        )
    elif new_status == "cancelled":
        # Notify candidate
        await create_and_push(
            db=db,
            user_id=candidate_user_id,
            type_="interview.cancelled",
            title="Interview abgesagt",
            body=f"Der Interview-Termin am {dt_str} wurde abgesagt.",
            meta={"schedule_id": str(schedule.id)},
        )

    return schedule


async def get_upcoming_interviews_for_reminder(
    db: AsyncSession,
) -> list[InterviewSchedule]:
    """
    Find confirmed interviews scheduled in the next 25h that haven't had a reminder sent.
    Called daily by APScheduler.
    """
    now = datetime.now(UTC)
    window_end = now + timedelta(hours=25)

    result = await db.execute(
        select(InterviewSchedule).where(
            InterviewSchedule.status == "confirmed",
            InterviewSchedule.scheduled_at >= now,
            InterviewSchedule.scheduled_at <= window_end,
            InterviewSchedule.reminder_sent_at.is_(None),
        )
    )
    return list(result.scalars().all())
