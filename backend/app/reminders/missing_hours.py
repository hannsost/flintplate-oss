"""Daily reminder for workers with missing/unsubmitted hours.

Runs every weekday at 18:00 – if a worker has open draft entries
older than 1 day, they receive a push notification.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import select

log = logging.getLogger(__name__)


async def send_missing_hours_reminders() -> None:
    from app.database import AsyncSessionLocal
    from app.notifications.service import create_and_push
    from app.worker.models import WorkerSettings
    from app.worker.time_models import TimeEntry

    yesterday = date.today() - timedelta(days=1)

    async with AsyncSessionLocal() as db:
        # Find draft entries from yesterday or earlier (worker forgot to submit)
        rows = await db.execute(
            select(TimeEntry.worker_id)
            .where(
                TimeEntry.status == "draft",
                TimeEntry.entry_date <= yesterday,
            )
            .distinct()
        )
        worker_ids = rows.scalars().all()

        if not worker_ids:
            return

        # Check those workers are still active
        ws_rows = await db.execute(
            select(WorkerSettings).where(
                WorkerSettings.user_id.in_(worker_ids),
                WorkerSettings.is_active == True,  # noqa: E712
            )
        )
        active_workers = {ws.user_id for ws in ws_rows.scalars()}

        notified = 0
        for worker_id in active_workers:
            try:
                await create_and_push(
                    db=db,
                    user_id=worker_id,
                    type_="worker_missing_hours",
                    title="Stunden noch nicht eingereicht",
                    body="Du hast offene Zeiteinträge vom Vortag. Bitte reiche sie zur Freigabe ein.",
                    meta={"link": "/worker/time"},
                )
                notified += 1
            except Exception:
                log.exception("Failed to notify worker %s for missing hours", worker_id)

        await db.commit()
        log.info("Missing-hours reminders sent: %d", notified)
