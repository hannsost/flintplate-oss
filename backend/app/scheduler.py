"""Dedicated scheduler: persist each due time slot, then let a worker execute it.

Run separately from HTTP workers with python -m app.scheduler.
Multiple schedulers are safe: the database deduplicates each time slot.
"""

from __future__ import annotations

import asyncio
import signal
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.database import AsyncSessionLocal, engine
from app.workqueue.service import enqueue

_scheduler: AsyncIOScheduler | None = None
ZONE = ZoneInfo("Europe/Berlin")


@dataclass(frozen=True)
class Schedule:
    trigger: BaseTrigger
    grace: int
    interval_seconds: int | None = None


SCHEDULES = {
    "check_stale_applications": Schedule(CronTrigger(hour=9, minute=0, timezone=ZONE), 3600),
    "send_interview_reminders": Schedule(CronTrigger(hour=8, minute=0, timezone=ZONE), 3600),
    "check_pipeline_sla": Schedule(
        IntervalTrigger(hours=1, start_date=datetime(2020, 1, 1, tzinfo=UTC)), 300, 3600
    ),
    "send_job_alert_notifications": Schedule(
        IntervalTrigger(hours=6, start_date=datetime(2020, 1, 1, tzinfo=UTC)), 600, 21600
    ),
    "run_scheduled_crawl": Schedule(CronTrigger(hour=3, minute=0, timezone=ZONE), 3600),
    "send_doc_expiry_notifications": Schedule(CronTrigger(hour=7, minute=0, timezone=ZONE), 3600),
    "send_missing_hours_reminders": Schedule(
        CronTrigger(hour=18, minute=0, day_of_week="mon-fri", timezone=ZONE), 1800
    ),
}


async def enqueue_scheduled(name: str, due: datetime | None = None) -> None:
    schedule = SCHEDULES[name]
    now = due or datetime.now(UTC)
    slot = (
        str(int(now.timestamp()) // schedule.interval_seconds)
        if schedule.interval_seconds
        else now.astimezone(ZONE).date().isoformat()
    )
    async with AsyncSessionLocal() as db, db.begin():
        await enqueue(
            db,
            kind="scheduled_job",
            key=f"{name}:{slot}",
            payload={"job_name": name},
            tenant_id=None,
            max_attempts=1,
            concurrency_key=f"schedule:{name}",
        )


async def catch_up(now: datetime) -> None:
    """Recover the most recent due slot within its documented grace window."""
    for name, schedule in SCHEDULES.items():
        due = schedule.trigger.get_next_fire_time(None, now - timedelta(seconds=schedule.grace))
        if due is not None and due <= now:
            await enqueue_scheduled(name, due)


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone=ZONE)
    return _scheduler


def start() -> None:
    scheduler = get_scheduler()
    for name, schedule in SCHEDULES.items():
        scheduler.add_job(
            enqueue_scheduled,
            schedule.trigger,
            args=[name],
            id=name,
            replace_existing=True,
            misfire_grace_time=schedule.grace,
            coalesce=True,
            max_instances=1,
        )
    scheduler.start()


def stop() -> None:
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)


async def main() -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app import model_registry  # noqa: F401

    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown.set)
    start()
    try:
        while not shutdown.is_set():
            with suppress(DBAPIError):
                # Failed persistence is retried within the grace window on the next tick.
                await catch_up(datetime.now(UTC))
                async with AsyncSessionLocal() as db:
                    await db.execute(text("SELECT 1"))
                Path("/tmp/palmscout-scheduler-heartbeat").touch()
            with suppress(TimeoutError):
                await asyncio.wait_for(shutdown.wait(), timeout=30)
    finally:
        stop()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
