"""Scheduled reminder jobs – Sprint 1.1."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.applications.models import Application, ApplicationStatus

log = logging.getLogger(__name__)

# Remind candidates whose application hasn't changed in this many days
STALE_AFTER_DAYS = 14


async def check_stale_applications() -> None:
    """Find stale open applications and send reminders. Runs daily at 09:00."""
    from app.database import AsyncSessionLocal
    from app.email.sender import send_reminder_email
    from app.notifications.service import create_and_push, reminder_already_sent

    stale_threshold = datetime.now(UTC) - timedelta(days=STALE_AFTER_DAYS)

    # Statuses where waiting too long without update means something is off
    active_statuses = [
        ApplicationStatus.APPLIED,
        ApplicationStatus.SCREENING,
        ApplicationStatus.INTERVIEW,
    ]

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Application)
            .where(Application.status.in_(active_statuses))
            .where(Application.updated_at < stale_threshold)
        )
        stale = list(result.scalars().all())
        log.info("Reminder scan: %d stale applications found", len(stale))

        sent = 0
        for app in stale:
            # Skip if we already reminded recently
            if await reminder_already_sent(db, app.user_id, app.id, within_days=7):
                continue

            days_idle = (datetime.now(UTC) - app.updated_at.replace(tzinfo=UTC)).days
            title = f"Hast du Neuigkeiten von {app.company}?"
            body = (
                f"Deine Bewerbung als **{app.position}** bei **{app.company}** "
                f"hat seit {days_idle} Tagen keinen Status-Update. "
                f"Vielleicht lohnt sich eine Nachfrage?"
            )
            meta = {"application_id": str(app.id), "company": app.company}

            await create_and_push(
                db,
                user_id=app.user_id,
                type_="reminder",
                title=title,
                body=body,
                meta=meta,
            )

            # Fire-and-forget email (non-blocking, optional)
            await send_reminder_email(app)
            sent += 1

        await db.commit()
        log.info("Reminders sent: %d", sent)
