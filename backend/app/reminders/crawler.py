"""Scheduled job: crawl and persist external/mock job postings – Sprint 2.1.

Env vars:
  JOB_CRAWLER_MOCK=true   – use mock generator instead of real RSS (default: true)
  JOB_CRAWLER_MOCK_COUNT  – number of mock jobs per run (default: 20)
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_USE_MOCK = os.getenv("JOB_CRAWLER_MOCK", "true").lower() in ("1", "true", "yes")
_MOCK_COUNT = int(os.getenv("JOB_CRAWLER_MOCK_COUNT", "20"))


async def run_scheduled_crawl() -> None:
    """Run all active job import sources via import_runner. Runs daily at 03:00."""
    from app.jobs.import_runner import run_all

    await run_all()
