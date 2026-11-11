"""Database queue behavior, including real concurrent sessions and stale claims."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.workqueue.models import WorkItem
from app.workqueue.service import claim_next, complete, current_claim, enqueue, fail


async def test_enqueue_rolls_back_with_business_transaction(db_session: AsyncSession) -> None:
    key = str(uuid.uuid4())
    nested = await db_session.begin_nested()
    item = await enqueue(
        db_session, kind="test", key=key, payload={"input": "test"}, tenant_id=None
    )
    item_id = item.id
    await nested.rollback()
    assert await db_session.scalar(select(WorkItem.id).where(WorkItem.id == item_id)) is None


async def test_deduplication_retry_and_lease_fencing(db_session: AsyncSession) -> None:
    key = str(uuid.uuid4())
    item = await enqueue(
        db_session, kind="test", key=key, payload={}, tenant_id=None, max_attempts=2
    )
    duplicate = await enqueue(
        db_session, kind="test", key=key, payload={}, tenant_id=None, max_attempts=2
    )
    assert item.id == duplicate.id
    first = await claim_next(db_session)
    assert first and first.id == item.id
    assert await claim_next(db_session) is None
    item.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()
    second = await claim_next(db_session)
    assert second and second.id == first.id and second.token != first.token
    assert await current_claim(db_session, first) is None
    await fail(db_session, first, "stale_error")
    assert item.status == "running"
    await fail(db_session, second, "synthetic_failure")
    assert item.status == "dead" and item.attempts == 2
    assert await claim_next(db_session) is None


async def test_retry_wait_and_expired_final_attempt(db_session: AsyncSession) -> None:
    item = await enqueue(
        db_session, kind="test", key=str(uuid.uuid4()), payload={}, tenant_id=None, max_attempts=2
    )
    first = await claim_next(db_session)
    assert first
    await fail(db_session, first, "temporary")
    assert item.status == "queued" and item.available_at > datetime.now(UTC)
    assert await claim_next(db_session) is None
    item.available_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()
    second = await claim_next(db_session)
    assert second
    item.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()
    assert await claim_next(db_session) is None
    await db_session.refresh(item)
    assert item.status == "dead" and item.last_error_code == "lease_exhausted"


async def test_real_workers_claim_distinct_items_and_serialize_agent() -> None:
    from tests.conftest import TestSessionLocal

    prefix = str(uuid.uuid4())
    # Separate committed test-schema records, so two actual DB connections can race.
    async with TestSessionLocal() as db, db.begin():
        for index in range(4):
            await enqueue(
                db,
                kind="test",
                key=f"{prefix}:{index}",
                payload={},
                tenant_id=None,
                concurrency_key=f"agent:{prefix}" if index < 2 else None,
            )

    async def take():
        async with TestSessionLocal() as db, db.begin():
            return await claim_next(db)

    claims = await asyncio.gather(take(), take(), take(), take())
    claimed = [claim for claim in claims if claim]
    assert len({claim.id for claim in claimed}) == len(claimed)
    async with TestSessionLocal() as db, db.begin():
        items = (
            await db.scalars(select(WorkItem).where(WorkItem.dedup_key.like(f"test:{prefix}:%")))
        ).all()
        assert (
            sum(item.status == "running" and item.concurrency_key is not None for item in items)
            == 1
        )
        for claim in claimed:
            item = await current_claim(db, claim)
            assert item
            complete(item)
    # Drain records from this test so other concurrent-session tests start cleanly.
    for _ in range(4):
        claim = await take()
        if claim:
            async with TestSessionLocal() as db, db.begin():
                item = await current_claim(db, claim)
                assert item
                complete(item)
