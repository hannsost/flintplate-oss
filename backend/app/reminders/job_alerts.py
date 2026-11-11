"""Scheduled job: send matching-job notifications to subscribers."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from html import escape

log = logging.getLogger(__name__)

# Only notify about jobs posted in the last N hours
CHECK_WINDOW_HOURS = 24


async def send_job_alert_notifications() -> None:
    """Check all active job alerts and send emails for new matching jobs. Runs every 6h."""

    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.jobs.models import JobAlert, JobPosting
    from app.jobs.publication import public_job_condition
    from app.users.models import User

    since = datetime.now(UTC) - timedelta(hours=CHECK_WINDOW_HOURS)

    async with AsyncSessionLocal() as db:
        # Get active alerts
        alerts_result = await db.execute(
            select(JobAlert).where(JobAlert.is_active == True)  # noqa: E712
        )
        alerts = alerts_result.scalars().all()
        if not alerts:
            return

        # Get new jobs in window
        new_jobs_result = await db.execute(
            select(JobPosting).where(JobPosting.published_at >= since, public_job_condition())
        )
        new_jobs = new_jobs_result.scalars().all()
        if not new_jobs:
            log.debug("Job alert scan: no new jobs in last %dh", CHECK_WINDOW_HOURS)
            return

        log.info("Job alert scan: %d new jobs, %d active alerts", len(new_jobs), len(alerts))

        from app.config import get_settings
        from app.email.sender import send_email
        from app.notifications.service import create_and_push

        _cfg = get_settings()
        _frontend_url = getattr(_cfg, "frontend_url", "http://localhost:3001")

        for alert in alerts:
            # Basic filter
            matched = []
            for job in new_jobs:
                if (
                    alert.last_sent_at
                    and job.published_at
                    and job.published_at <= alert.last_sent_at
                ):
                    continue
                if not await db.scalar(
                    select(JobPosting.id).where(JobPosting.id == job.id, public_job_condition())
                ):
                    continue
                if alert.remote_only and not job.is_remote:
                    continue
                if alert.min_salary and job.salary_min and job.salary_min < alert.min_salary:
                    continue
                if alert.category and job.category != alert.category:
                    continue
                if alert.location and alert.location.lower() not in (job.location or "").lower():
                    continue
                if alert.keywords:
                    kw = alert.keywords.lower()
                    text = f"{job.title} {job.description or ''}".lower()
                    if kw not in text:
                        continue
                matched.append(job)

            if not matched:
                continue

            # Get user
            user_result = await db.execute(select(User).where(User.id == alert.user_id))
            user = user_result.scalar_one_or_none()
            if not user or not user.is_active:
                continue

            # Create in-app notification
            await create_and_push(
                db=db,
                user_id=alert.user_id,
                type_="job_alert",
                title=f"{len(matched)} neue Jobs für dich",
                body=f"Basierend auf deinem Job-Alarm: {', '.join(j.title for j in matched[:3])}{'…' if len(matched) > 3 else ''}",
                meta={"alert_id": str(alert.id), "count": len(matched)},
            )

            # Send email
            job_rows = "".join(
                f"<li><a href='{_frontend_url}/jobs' style='color:#2563eb'>{escape(j.title)}</a> · {escape(j.company)}{' · ' + escape(j.location) if j.location else ''}</li>"
                for j in matched[:10]
            )
            await send_email(
                to=user.email,
                subject=f"{len(matched)} neue Jobs für dich",
                html=f"""
                <div style="font-family:sans-serif;max-width:560px;margin:auto;padding:24px">
                  <h2 style="color:#1a1a2e">{len(matched)} neue Jobs passen zu deinem Alarm</h2>
                  <ul style="padding-left:16px;line-height:2">{job_rows}</ul>
                  <a href="{_frontend_url}/jobs"
                     style="display:inline-block;margin-top:16px;padding:10px 20px;
                            background:#2563eb;color:#fff;border-radius:8px;text-decoration:none">
                    Alle Jobs ansehen
                  </a>
                  <p style="margin-top:32px;color:#888;font-size:12px">
                    Job-Alarme können in den <a href="{_frontend_url}/settings">Einstellungen</a> verwaltet werden.
                  </p>
                </div>
                """,
            )

            # Update last_sent_at
            alert.last_sent_at = datetime.now(UTC)

        await db.commit()
