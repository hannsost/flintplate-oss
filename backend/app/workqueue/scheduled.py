"""Fixed scheduled handlers; delivery uncertainty requires operator review."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.database import AsyncSessionLocal
from app.workqueue.service import Claim, complete, current_claim


async def execute(claim: Claim) -> None:
    from app.pipeline.jobs import check_pipeline_sla
    from app.reminders.crawler import run_scheduled_crawl
    from app.reminders.doc_expiry import send_doc_expiry_notifications
    from app.reminders.interview import send_interview_reminders
    from app.reminders.job_alerts import send_job_alert_notifications
    from app.reminders.jobs import check_stale_applications
    from app.reminders.missing_hours import send_missing_hours_reminders

    handlers: dict[str, Callable[[], Awaitable[None]]] = {
        handler.__name__: handler
        for handler in (
            check_pipeline_sla,
            run_scheduled_crawl,
            send_doc_expiry_notifications,
            send_interview_reminders,
            send_job_alert_notifications,
            check_stale_applications,
            send_missing_hours_reminders,
        )
    }
    handler = handlers.get(claim.payload["job_name"])
    if handler is None:
        raise ValueError("Unknown scheduled handler")
    # A single reserved attempt: legacy/SMTP handlers cannot generally prove
    # whether a remote side effect succeeded after a crash.
    async with AsyncSessionLocal() as db:
        if await current_claim(db, claim) is None:
            return
    await handler()
    async with AsyncSessionLocal() as db, db.begin():
        item = await current_claim(db, claim)
        if item is not None:
            complete(item)
