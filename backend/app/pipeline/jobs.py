"""Scheduled jobs for Pipeline Builder – SLA breach detection."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


async def check_pipeline_sla() -> None:
    """Hourly: find pipeline stage assignments that have exceeded their SLA and notify."""
    from app.database import AsyncSessionLocal
    from app.pipeline.service import check_sla_breaches

    try:
        async with AsyncSessionLocal() as db:
            breaches = await check_sla_breaches(db)
            await db.commit()
            if breaches:
                log.info("Pipeline SLA: %d breach(es) detected", len(breaches))
            else:
                log.debug("Pipeline SLA: no breaches")
    except Exception as exc:
        log.exception("Pipeline SLA check failed: %s", exc)
