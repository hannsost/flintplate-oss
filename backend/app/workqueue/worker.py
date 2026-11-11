"""Dedicated worker entry point: python -m app.workqueue.worker.

No HTTP scheduler, arbitrary tools, shell jobs, or implicit external sends.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import uuid
from contextlib import suppress
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app import model_registry  # noqa: F401
from app.database import AsyncSessionLocal, engine
from app.jobs.models import JobPosting
from app.workqueue.service import Claim, claim_next, complete, current_claim, fail

log = logging.getLogger(__name__)


async def embedding(claim: Claim) -> None:
    from app.jobs.embeddings import embed_job

    job_id = uuid.UUID(claim.payload["job_id"])
    version = int(claim.payload["version"])
    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(JobPosting).where(JobPosting.id == job_id))
        source = (job.title, job.description) if job and job.version == version else None
    vector = await embed_job(*source) if source else None
    async with AsyncSessionLocal() as db, db.begin():
        item = await current_claim(db, claim)
        if item is None:
            return
        job = await db.scalar(select(JobPosting).where(JobPosting.id == job_id).with_for_update())
        if vector is not None and job and job.version == version:
            job.embedding = vector
        complete(item)


async def run_once() -> bool:
    async with AsyncSessionLocal() as db, db.begin():
        claim = await claim_next(db)
    if claim is None:
        return False
    try:
        async with asyncio.timeout(60):
            if claim.kind == "job_embedding":
                await embedding(claim)
            elif claim.kind == "agent_task":
                from app.agents.execution import execute

                await execute(claim)
            elif claim.kind == "scheduled_job":
                from app.workqueue.scheduled import execute as execute_scheduled

                await execute_scheduled(claim)
            else:
                async with AsyncSessionLocal() as db, db.begin():
                    await fail(db, claim, "unknown_work_kind", retry=False)
    except (TimeoutError, DBAPIError, OSError, ValueError, KeyError) as exc:
        # Codes only: provider responses, payloads and credentials never enter logs.
        code = type(exc).__name__
        log.warning("Work item failed: %s (%s)", claim.id, code)
        async with AsyncSessionLocal() as db, db.begin():
            await fail(db, claim, code)
    return True


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        while not stop.is_set():
            try:
                handled = await run_once()
                Path("/tmp/palmscout-worker-heartbeat").touch()
            except DBAPIError:
                log.warning("Work queue database temporarily unavailable")
                handled = False
            if not handled:
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=2)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
