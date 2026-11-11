"""Import persistence, duplicate handling and operator-visible run results."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs import import_runner
from app.jobs.models import JobPosting
from app.jobs.models_import import JobImportRun
from app.jobs.schemas import JobPostingCreate


@pytest.fixture(autouse=True)
def isolated_import_sessions(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr("app.database.AsyncSessionLocal", session)
    monkeypatch.setattr(import_runner, "_USE_MOCK", True)


async def test_import_deduplicates_and_records_run_totals(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vacancy = JobPostingCreate(
        title="Python Engineer",
        company="Synthetic Import",
        url="https://example.com/job-one",
        source="mock",
    )
    monkeypatch.setattr(
        "app.jobs.crawler.generate_mock_jobs", AsyncMock(return_value=[vacancy, vacancy])
    )
    first_id = await import_runner.run_and_log("mock")
    first = await db_session.get(JobImportRun, first_id)
    assert first is not None and first.status == "done"
    assert first.jobs_found == 2 and first.jobs_new == 1 and first.finished_at is not None
    second_id = await import_runner.run_and_log("mock")
    second = await db_session.get(JobImportRun, second_id)
    assert second is not None and second.jobs_new == 0
    jobs = list((await db_session.execute(select(JobPosting))).scalars())
    assert len(jobs) == 1 and len(jobs[0].embedding) == 384
    assert jobs[0].category == "IT/Software"


@pytest.mark.parametrize("source", ["bundesagentur", "remotive"])
async def test_external_source_adapters_persist_without_real_network(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    if source == "bundesagentur":
        fetch = AsyncMock(
            return_value=[
                {
                    "title": "Recruiter",
                    "company": "Synthetic Source",
                    "external_id": "synthetic-import-id",
                    "source": source,
                }
            ]
        )
        monkeypatch.setattr("app.jobs.sources.bundesagentur.fetch_bundesagentur_jobs", fetch)
    else:
        fetch = AsyncMock(
            return_value=[
                JobPostingCreate(
                    title="Recruiter",
                    company="Synthetic Source",
                    source=source,
                    url="https://example.com/import-rss",
                )
            ]
        )
        monkeypatch.setattr("app.jobs.crawler.fetch_rss_jobs", fetch)
    assert await import_runner.run_source(source) == (1, 1)
    assert await import_runner.run_source(source) == (1, 0)
    persisted = (await db_session.execute(select(JobPosting))).scalar_one()
    assert persisted.source == source and persisted.owner_id is None


async def test_scheduler_imports_and_failure_reports(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.jobs.crawler.generate_mock_jobs", AsyncMock(return_value=[]))
    await import_runner.run_all()
    run = (await db_session.execute(select(JobImportRun))).scalar_one()
    assert run.status == "done" and run.jobs_new == 0
    monkeypatch.setattr(
        "app.jobs.crawler.generate_mock_jobs",
        AsyncMock(side_effect=OSError("Synthetic source unavailable")),
    )
    failed = await import_runner.run_and_log("mock")
    result = await db_session.get(JobImportRun, failed)
    assert result is not None and result.status == "error"
    assert result.error_msg == "Synthetic source unavailable" and result.finished_at is not None
    assert await import_runner.run_source("unconfigured-source") == (0, 0)
    monkeypatch.setattr(import_runner, "_USE_MOCK", False)
    assert "bundesagentur" in import_runner._active_sources()
