"""Interview 24h-Reminder – Sprint 1.5."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

log = logging.getLogger(__name__)


async def send_interview_reminders() -> None:
    """
    Called daily by APScheduler.
    Finds confirmed interviews in the next 25 hours that haven't had a reminder
    sent yet, then notifies both the candidate and the recruiter.
    """
    from sqlalchemy import select

    from app.applications.models import Application
    from app.database import AsyncSessionLocal
    from app.interviews.service import get_upcoming_interviews_for_reminder
    from app.jobs.models import JobPosting
    from app.notifications.service import create_and_push
    from app.users.models import User

    async with AsyncSessionLocal() as db:
        schedules = await get_upcoming_interviews_for_reminder(db)

        if not schedules:
            log.info("Interview reminders: nothing due.")
            return

        for schedule in schedules:
            try:
                # Load application
                app_result = await db.execute(
                    select(Application).where(Application.id == schedule.application_id)
                )
                app = app_result.scalar_one_or_none()
                if not app:
                    continue

                dt_str = schedule.scheduled_at.strftime("%d.%m.%Y um %H:%M Uhr")

                # Notify candidate
                await create_and_push(
                    db=db,
                    user_id=app.user_id,
                    type_="interview.reminder",
                    title="Interview morgen!",
                    body=f"Erinnerung: Dein Interview für '{app.position}' findet am {dt_str} statt.",
                    meta={
                        "schedule_id": str(schedule.id),
                        "scheduled_at": schedule.scheduled_at.isoformat(),
                        "meeting_url": schedule.meeting_url,
                    },
                )

                # Notify recruiter (job owner)
                recruiter_id = None
                if app.job_id:
                    job_result = await db.execute(
                        select(JobPosting).where(JobPosting.id == app.job_id)
                    )
                    job = job_result.scalar_one_or_none()
                    if job and job.owner_id:
                        recruiter_id = job.owner_id

                        # Fetch candidate name
                        user_result = await db.execute(select(User).where(User.id == app.user_id))
                        candidate = user_result.scalar_one_or_none()
                        name = (candidate.full_name or "Kandidat") if candidate else "Kandidat"

                        await create_and_push(
                            db=db,
                            user_id=recruiter_id,
                            type_="interview.reminder",
                            title="Interview morgen",
                            body=f"Erinnerung: Interview mit {name} für '{app.position}' am {dt_str}.",
                            meta={
                                "schedule_id": str(schedule.id),
                                "scheduled_at": schedule.scheduled_at.isoformat(),
                            },
                        )

                # Mark reminder as sent
                schedule.reminder_sent_at = datetime.now(UTC)

            except Exception as exc:
                log.exception(
                    "Failed to send interview reminder for schedule %s: %s", schedule.id, exc
                )

        await db.commit()
        log.info("Interview reminders: %d reminders sent.", len(schedules))
