"""Advance durable in-app requests even when no browser is polling."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.admin.models import Customer
from app.database import AsyncSessionLocal
from app.gastro.emergency import advance
from app.gastro.models import Emergency, Venue

logger = logging.getLogger(__name__)


async def tick() -> None:
    async with AsyncSessionLocal() as db:
        ids = list(
            (
                await db.execute(
                    select(Emergency.venue_id).where(Emergency.status == "open").distinct()
                )
            ).scalars()
        )
    for venue_id in ids:
        async with AsyncSessionLocal.begin() as db:
            # Same lock as user actions. Multiple API processes may safely tick.
            venue = (
                await db.execute(
                    select(Venue)
                    .join(Customer, Customer.id == Venue.tenant_id)
                    .where(Venue.id == venue_id, Customer.status.in_(["active", "trial"]))
                    .with_for_update(of=Venue, key_share=True, skip_locked=True)
                )
            ).scalar_one_or_none()
            if venue is None:
                continue
            requests = (
                (
                    await db.execute(
                        select(Emergency).where(
                            Emergency.venue_id == venue_id, Emergency.status == "open"
                        )
                    )
                )
                .scalars()
                .all()
            )
            for request in requests:
                await advance(db, request)


async def run() -> None:
    while True:
        try:
            await tick()
        except SQLAlchemyError:
            # No credentials, request payloads or personal data in operational logs.
            logger.error("FlintPlate replacement scheduler database operation failed; retrying.")
        await asyncio.sleep(15)
