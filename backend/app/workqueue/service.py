"""At-least-once claims with fenced, transactional completion and bounded retry."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.workqueue.models import WorkItem

LEASE_SECONDS = 90


@dataclass(frozen=True)
class Claim:
    id: uuid.UUID
    token: uuid.UUID
    kind: str
    payload: dict[str, str]


async def enqueue(
    db: AsyncSession,
    *,
    kind: str,
    key: str,
    payload: dict[str, str],
    tenant_id: uuid.UUID | None,
    max_attempts: int = 3,
    concurrency_key: str | None = None,
) -> WorkItem:
    key = f"{kind}:{key}"
    await db.execute(
        insert(WorkItem)
        .values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            kind=kind,
            dedup_key=key,
            payload=payload,
            max_attempts=max_attempts,
            concurrency_key=concurrency_key,
        )
        .on_conflict_do_nothing(index_elements=[WorkItem.dedup_key])
    )
    item = await db.scalar(select(WorkItem).where(WorkItem.dedup_key == key))
    if item is None or item.payload != payload or item.tenant_id != tenant_id:
        raise ValueError("Work key reused with a different payload or tenant")
    return item


async def claim_next(db: AsyncSession) -> Claim | None:
    now = datetime.now(UTC)
    await db.execute(
        update(WorkItem)
        .where(
            WorkItem.status == "running",
            WorkItem.lease_until <= now,
            WorkItem.attempts >= WorkItem.max_attempts,
        )
        .values(
            status="dead",
            claim_token=None,
            lease_until=None,
            last_error_code="lease_exhausted",
            updated_at=now,
        )
    )
    other = aliased(WorkItem)
    occupied = (
        select(other.id)
        .where(
            other.id != WorkItem.id,
            other.concurrency_key == WorkItem.concurrency_key,
            other.status == "running",
            other.lease_until > now,
        )
        .correlate(WorkItem)
        .exists()
    )
    item = await db.scalar(
        select(WorkItem)
        .where(
            or_(
                and_(WorkItem.status == "queued", WorkItem.available_at <= now),
                and_(WorkItem.status == "running", WorkItem.lease_until <= now),
            ),
            WorkItem.attempts < WorkItem.max_attempts,
            or_(WorkItem.concurrency_key.is_(None), ~occupied),
        )
        .order_by(WorkItem.available_at, WorkItem.created_at, WorkItem.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if item is None:
        return None
    if item.concurrency_key:
        key = int.from_bytes(
            hashlib.sha256(item.concurrency_key.encode()).digest()[:8], signed=True
        )
        if not await db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}):
            return None
        # A different worker may have committed a claim since the first SELECT.
        busy = await db.scalar(
            select(WorkItem.id)
            .where(
                WorkItem.id != item.id,
                WorkItem.concurrency_key == item.concurrency_key,
                WorkItem.status == "running",
                WorkItem.lease_until > datetime.now(UTC),
            )
            .limit(1)
        )
        if busy is not None:
            return None
    item.status = "running"
    item.attempts += 1
    item.claim_token = uuid.uuid4()
    item.lease_until = now + timedelta(seconds=LEASE_SECONDS)
    item.updated_at = now
    await db.flush()
    return Claim(item.id, item.claim_token, item.kind, dict(item.payload))


async def current_claim(db: AsyncSession, claim: Claim) -> WorkItem | None:
    item: WorkItem | None = await db.scalar(
        select(WorkItem)
        .where(
            WorkItem.id == claim.id,
            WorkItem.claim_token == claim.token,
            WorkItem.status == "running",
            WorkItem.lease_until > datetime.now(UTC),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )

    return item


def complete(item: WorkItem) -> None:
    item.status = "completed"
    item.claim_token = None
    item.lease_until = None
    item.last_error_code = None
    item.updated_at = datetime.now(UTC)


async def fail(db: AsyncSession, claim: Claim, code: str, *, retry: bool = True) -> None:
    item = await current_claim(db, claim)
    if item is None:
        return
    item.status = "queued" if retry and item.attempts < item.max_attempts else "dead"
    item.available_at = datetime.now(UTC) + timedelta(seconds=min(300, 5 * 2**item.attempts))
    item.last_error_code = code
    item.claim_token = None
    item.lease_until = None
    item.updated_at = datetime.now(UTC)


async def enqueue_embedding(
    db: AsyncSession, job_id: uuid.UUID, version: int, tenant_id: uuid.UUID | None
) -> None:
    await enqueue(
        db,
        kind="job_embedding",
        key=f"{job_id}:{version}",
        payload={"job_id": str(job_id), "version": str(version)},
        tenant_id=tenant_id,
    )
