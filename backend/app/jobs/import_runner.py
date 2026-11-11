"""Job import runner – Sprint 2.5.

Orchestrates all job sources, deduplicates, embeds, persists and logs runs.
Can be called from the scheduler or triggered manually via the admin API.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

_USE_MOCK = os.getenv("JOB_CRAWLER_MOCK", "true").lower() in ("1", "true", "yes")
_MOCK_COUNT = int(os.getenv("JOB_CRAWLER_MOCK_COUNT", "20"))


async def run_source(source: str) -> tuple[int, int]:
    """Run a single named source. Returns (jobs_found, jobs_new)."""
    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.jobs.embeddings import embed_job
    from app.jobs.models import JobPosting
    from app.jobs.service import classify_category

    raw_jobs: list[dict[str, Any]] = []

    if source == "mock":
        from app.jobs.crawler import generate_mock_jobs

        items = await generate_mock_jobs(_MOCK_COUNT)
        raw_jobs = [
            {
                "title": j.title,
                "company": j.company,
                "location": getattr(j, "location", None),
                "description": getattr(j, "description", None),
                "url": getattr(j, "url", None),
                "source": getattr(j, "source", "mock"),
                "external_id": j.external_id or j.url,
                "is_remote": getattr(j, "is_remote", False),
                "salary_min": getattr(j, "salary_min", None),
                "salary_max": getattr(j, "salary_max", None),
                "required_skills": getattr(j, "required_skills", []),
                "published_at": j.posted_at,
            }
            for j in items
        ]
    elif source == "bundesagentur":
        from app.jobs.sources.bundesagentur import fetch_bundesagentur_jobs

        raw_jobs = await fetch_bundesagentur_jobs(keywords="developer", location="Deutschland")
    else:
        # Generic RSS feed
        from app.jobs.crawler import FEED_URLS, fetch_rss_jobs

        if source in FEED_URLS:
            items = await fetch_rss_jobs(FEED_URLS[source], source)
            raw_jobs = [
                {
                    "title": j.title,
                    "company": j.company,
                    "location": getattr(j, "location", None),
                    "description": getattr(j, "description", None),
                    "url": getattr(j, "url", None),
                    "source": getattr(j, "source", source),
                    "external_id": j.external_id or j.url,
                    "is_remote": False,
                    "salary_min": None,
                    "salary_max": None,
                    "required_skills": [],
                    "published_at": j.posted_at,
                }
                for j in items
            ]

    if not raw_jobs:
        return 0, 0

    jobs_found = len(raw_jobs)
    jobs_new = 0

    async with AsyncSessionLocal() as db:
        for data in raw_jobs:
            ext_id: str | None = data.get("external_id") or None
            if ext_id:
                result = await db.execute(
                    select(JobPosting).where(JobPosting.external_id == ext_id)
                )
                if result.scalar_one_or_none() is not None:
                    continue

            embedding = await embed_job(data.get("title", ""), data.get("description"))
            job = JobPosting(
                title=data["title"],
                company=data["company"],
                category=classify_category(data["title"], data.get("description")),
                location=data.get("location"),
                description=data.get("description"),
                url=data.get("url"),
                source=data.get("source", source),
                external_id=ext_id,
                is_remote=data.get("is_remote", False),
                salary_min=data.get("salary_min"),
                salary_max=data.get("salary_max"),
                required_skills=data.get("required_skills", []),
                embedding=embedding,
                posted_at=data.get("published_at"),
            )
            db.add(job)
            jobs_new += 1

        await db.commit()

    log.info("Source %s: found=%d new=%d", source, jobs_found, jobs_new)
    return jobs_found, jobs_new


async def run_all() -> None:
    """Run all configured sources and log results to job_import_runs."""
    sources = _active_sources()
    for source in sources:
        await run_and_log(source)


async def run_and_log(source: str) -> uuid.UUID:
    """Run a single source and persist a JobImportRun record. Returns the run ID."""
    from app.database import AsyncSessionLocal
    from app.jobs.models_import import JobImportRun

    run_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        run = JobImportRun(id=run_id, source=source, status="running")
        db.add(run)
        await db.commit()

    jobs_found = 0
    jobs_new = 0
    error_msg: str | None = None

    try:
        jobs_found, jobs_new = await run_source(source)
        status = "done"
    except Exception as exc:
        log.exception("Import run failed for source=%s", source)
        error_msg = str(exc)
        status = "error"

    async with AsyncSessionLocal() as db:
        finished_run = await db.get(JobImportRun, run_id)
        if finished_run:
            finished_run.status = status
            finished_run.jobs_found = jobs_found
            finished_run.jobs_new = jobs_new
            finished_run.error_msg = error_msg
            finished_run.finished_at = datetime.now(UTC)
            await db.commit()

    return run_id


def _active_sources() -> list[str]:
    """Return list of active import sources based on env config."""
    if _USE_MOCK:
        return ["mock"]
    sources = ["bundesagentur"]
    # Add RSS sources if configured
    from app.jobs.crawler import FEED_URLS

    sources.extend(FEED_URLS.keys())
    return sources
