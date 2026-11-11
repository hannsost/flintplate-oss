"""Schedulers persist deduplicated slots and use German wall-clock schedules."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import scheduler
from app.workqueue.models import WorkItem


async def test_two_schedulers_enqueue_one_slot(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await db_session.commit()

    def sessions():
        return AsyncSession(
            bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )

    monkeypatch.setattr(scheduler, "AsyncSessionLocal", sessions)
    due = datetime(2026, 9, 10, 7, tzinfo=UTC)
    for _ in range(2):
        await scheduler.enqueue_scheduled("check_stale_applications", due)
    items = (await db_session.scalars(select(WorkItem))).all()
    assert len(items) == 1
    assert items[0].payload == {"job_name": "check_stale_applications"}
    assert items[0].status == "queued" and items[0].max_attempts == 1


@pytest.mark.parametrize("month,expected_utc_hour", [(1, 8), (7, 7)])
def test_german_nine_am_is_stable_across_summer_time(month: int, expected_utc_hour: int) -> None:
    trigger = scheduler.SCHEDULES["check_stale_applications"].trigger
    due = trigger.get_next_fire_time(None, datetime(2026, month, 10, tzinfo=UTC))
    assert due and due.hour == 9 and due.astimezone(UTC).hour == expected_utc_hour


async def test_startup_recovers_due_work_within_grace_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueue = AsyncMock()
    monkeypatch.setattr(scheduler, "enqueue_scheduled", enqueue)
    await scheduler.catch_up(datetime(2026, 9, 10, 7, 2, tzinfo=UTC))
    names = [call.args[0] for call in enqueue.await_args_list]
    assert "check_stale_applications" in names
    assert "check_pipeline_sla" in names
    assert "send_interview_reminders" not in names


@pytest.mark.parametrize("outcome", ["success", "timeout", "stale"])
async def test_scheduled_dispatch_and_uncertain_delivery_are_not_repeated(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    from app.workqueue import scheduled, worker
    from app.workqueue.service import claim_next, enqueue

    calls = 0

    async def check_pipeline_sla() -> None:
        nonlocal calls
        calls += 1
        if outcome == "timeout":
            raise TimeoutError("Synthetic uncertain delivery")

    def sessions():
        return AsyncSession(
            bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )

    monkeypatch.setattr("app.pipeline.jobs.check_pipeline_sla", check_pipeline_sla)
    monkeypatch.setattr(worker, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(scheduled, "AsyncSessionLocal", sessions)
    item = await enqueue(
        db_session,
        kind="scheduled_job",
        key=str(uuid.uuid4()),
        payload={"job_name": "check_pipeline_sla"},
        tenant_id=None,
        max_attempts=1,
    )
    if outcome == "stale":
        claim = await claim_next(db_session)
        assert claim
        item.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.commit()
        await scheduled.execute(claim)
        assert calls == 0
    else:
        await db_session.commit()
        assert await worker.run_once()
        await db_session.refresh(item)
        assert calls == 1
        assert item.status == ("completed" if outcome == "success" else "dead")
    assert not await worker.run_once()
    assert calls == (0 if outcome == "stale" else 1)
