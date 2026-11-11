"""Jobs endpoints – Sprint 0.4."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from contextlib import suppress
from datetime import UTC
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import check_module_enabled, track_ai_usage
from app.database import get_db
from app.jobs.models import JobPosting, JobPublicationEvent
from app.jobs.publication import (
    change_publication,
    check_version,
    public_job_condition,
    require_public_job,
)
from app.jobs.schemas import (
    JobAlertCreate,
    JobAlertRead,
    JobFeedResponse,
    JobFilter,
    JobMatchRequest,
    JobMatchResult,
    JobPostingCreate,
    JobPostingRead,
    JobPostingUpdate,
    JobPublicationChange,
    JobPublicationEventRead,
    MarketStats,
    RecruiterApplicationUpdate,
)
from app.jobs.service import (
    apply_to_job,
    create_job,
    create_recruiter_job,
    delete_recruiter_job,
    get_applications_for_job,
    get_candidates_for_job,
    get_market_stats,
    get_recommended_jobs,
    list_my_jobs,
    match_profile_to_job,
    update_application_as_recruiter,
    update_recruiter_job,
)
from app.profiles.service import get_or_create_profile
from app.security import get_current_user
from app.users.models import User
from app.workqueue.service import enqueue_embedding

log = logging.getLogger(__name__)

router = APIRouter()
PROFILE_EMBED_BUDGET_SECONDS = 2.0


# ── Seed / Admin ──────────────────────────────────────────────────────────────


@router.post(
    "/seed",
    status_code=status.HTTP_201_CREATED,
    summary="Testjobs einspielen (Dev only)",
    include_in_schema=True,
)
async def seed_jobs(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    from datetime import datetime, timedelta

    from app.config import get_settings
    from app.jobs.crawler import generate_mock_jobs

    if get_settings().app_env not in {"development", "test"}:
        raise HTTPException(404, "Nicht verfügbar.")
    if current_user.role != "admin" or current_user.tenant_id is not None:
        raise HTTPException(403, "Nur für die Plattformadministration.")

    jobs_data = await generate_mock_jobs(count=30)
    created = 0
    for data in jobs_data:
        job = await create_job(db, data)
        if job:
            job.publication_status = "published"
            job.published_at = datetime.now(UTC)
            job.expires_at = job.published_at + timedelta(days=30)
            # Embed immediately
            from app.jobs.embeddings import embed_job

            if job.embedding is None:
                job.embedding = await embed_job(job.title, job.description)
            created += 1
    await db.commit()
    return {"seeded": created}


# ── Recommended feed ──────────────────────────────────────────────────────────


@router.get(
    "/recommended",
    response_model=JobFeedResponse,
    status_code=200,
    summary="Empfohlene Jobs mit Match-Score",
)
async def get_recommended(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    remote_only: bool = Query(False),
    min_salary: int | None = Query(None),
    location: str | None = Query(None),
    category: str | None = Query(None),
    text_search: str | None = Query(None),
    skills: list[str] = Query(default=[]),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> JobFeedResponse:
    from app.jobs.embeddings import embed_profile

    profile = await get_or_create_profile(db, current_user.id)
    profile_skills = [s.name for s in profile.skills]

    try:
        async with asyncio.timeout(PROFILE_EMBED_BUDGET_SECONDS):
            profile_embedding = await embed_profile(
                headline=profile.headline,
                summary=profile.summary,
                skills=profile_skills,
            )
    except TimeoutError:
        # Cold model loading may continue in its thread. Serve the explicitly
        # labelled skill-only feed immediately; the model never blocks browsing.
        profile_embedding = []

    filters = JobFilter(
        remote_only=remote_only,
        min_salary=min_salary,
        location=location,
        category=category,
        text_search=text_search,
        skills=skills,
        page=page,
        page_size=page_size,
    )

    results, total = await get_recommended_jobs(
        db=db,
        profile_id=profile.id,
        profile_skills=profile_skills,
        profile_embedding=profile_embedding,
        filters=filters,
    )

    return JobFeedResponse(
        jobs=results,
        total=total,
        page=page,
        page_size=page_size,
    )


# ── Scraper Import ────────────────────────────────────────────────────────────


class JobImportRequest(BaseModel):
    jobs: list[JobPostingCreate]


class JobCloseRequest(BaseModel):
    external_ids: list[str]


@router.get(
    "/import-review",
    response_model=list[JobPostingRead],
    status_code=200,
    summary="Importierte Inserate zur Veröffentlichung prüfen (Plattformadministration)",
)
async def imported_publication_queue(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    offset: int = Query(0, ge=0),
) -> list[JobPostingRead]:
    if current_user.role != "admin" or current_user.tenant_id is not None:
        raise HTTPException(403, "Nur für die Plattformadministration.")
    rows = await db.scalars(
        select(JobPosting)
        .where(
            JobPosting.owner_id.is_(None),
            JobPosting.tenant_id.is_(None),
            JobPosting.source != "recruiter",
            JobPosting.publication_status != "archived",
        )
        .order_by(JobPosting.created_at.desc(), JobPosting.id)
        .offset(offset)
        .limit(50)
    )
    return [JobPostingRead.model_validate(job) for job in rows]


@router.post(
    "/import-review/{job_id}/publication/{action}",
    response_model=JobPostingRead,
    status_code=200,
    summary="Veröffentlichung eines Imports entscheiden (Plattformadministration)",
)
async def review_import_publication(
    job_id: uuid.UUID,
    action: str,
    data: JobPublicationChange,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JobPostingRead:
    from typing import Literal, cast

    if current_user.role != "admin" or current_user.tenant_id is not None:
        raise HTTPException(403, "Nur für die Plattformadministration.")
    if action not in {"publish", "withdraw", "archive"}:
        raise HTTPException(422, "Unbekannte Veröffentlichungsaktion.")
    job = await db.scalar(
        select(JobPosting)
        .where(
            JobPosting.id == job_id,
            JobPosting.owner_id.is_(None),
            JobPosting.tenant_id.is_(None),
            JobPosting.source != "recruiter",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        raise HTTPException(404, "Import nicht gefunden.")
    await change_publication(
        db, job, current_user.id, cast(Literal["publish", "withdraw", "archive"], action), data
    )
    if action == "publish" and job.embedding is None:
        await enqueue_embedding(db, job.id, job.version, job.tenant_id)
    await db.commit()
    return JobPostingRead.model_validate(job)


@router.patch(
    "/import-review/{job_id}",
    response_model=JobPostingRead,
    status_code=200,
    summary="Importierte Stellenangaben vor Veröffentlichung ergänzen",
)
async def edit_imported_job(
    job_id: uuid.UUID,
    data: JobPostingUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JobPostingRead:
    if current_user.role != "admin" or current_user.tenant_id is not None:
        raise HTTPException(403, "Nur für die Plattformadministration.")
    job = await db.scalar(
        select(JobPosting)
        .where(
            JobPosting.id == job_id,
            JobPosting.owner_id.is_(None),
            JobPosting.tenant_id.is_(None),
            JobPosting.source != "recruiter",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        raise HTTPException(404, "Import nicht gefunden.")
    await update_recruiter_job(db, job, data, actor_id=current_user.id)
    await enqueue_embedding(db, job.id, job.version, None)
    await db.commit()
    return JobPostingRead.model_validate(job)


def _verify_import_key(x_import_key: str) -> None:
    from secrets import compare_digest

    from app.config import get_settings

    configured = get_settings().scraper_import_key
    if not configured or not compare_digest(x_import_key, configured):
        raise HTTPException(status_code=401, detail="Ungültiger Import-Key.")


async def _embed_new_jobs(job_ids: list[uuid.UUID]) -> None:
    """Background task: compute embeddings for newly imported jobs."""
    from app.database import AsyncSessionLocal
    from app.jobs.embeddings import embed_job
    from app.jobs.models import JobPosting

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(JobPosting)
            .where(JobPosting.id.in_(job_ids))
            .where(JobPosting.embedding.is_(None))
        )
        jobs = result.scalars().all()
        for job in jobs:
            job.embedding = await embed_job(job.title, job.description)
        await db.commit()
    log.info("Background embedding: %d jobs embedded", len(jobs))


@router.post(
    "/import",
    status_code=status.HTTP_200_OK,
    summary="Bulk-Import von Jobs durch den Job-Scraper (API-Key Auth)",
    include_in_schema=True,
)
async def import_jobs(
    data: JobImportRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
    x_import_key: str = Header(..., alias="X-Import-Key"),
) -> dict[str, Any]:
    _verify_import_key(x_import_key)

    imported = skipped = 0
    new_job_ids: list[uuid.UUID] = []
    for job_data in data.jobs:
        job = await create_job(db, job_data)
        if job:
            imported += 1
            new_job_ids.append(job.id)
        else:
            skipped += 1

    for job_id in new_job_ids:
        await enqueue_embedding(db, job_id, 1, None)
    await db.commit()

    return {"imported": imported, "skipped": skipped, "total": len(data.jobs)}


@router.delete(
    "/import",
    status_code=status.HTTP_200_OK,
    summary="Abgelaufene Scraper-Jobs entfernen (API-Key Auth)",
    include_in_schema=True,
)
async def remove_imported_jobs(
    data: JobCloseRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_import_key: str = Header(..., alias="X-Import-Key"),
) -> dict[str, Any]:
    _verify_import_key(x_import_key)
    jobs = (
        await db.scalars(
            select(JobPosting)
            .where(
                JobPosting.external_id.in_(data.external_ids),
                JobPosting.owner_id.is_(None),
                JobPosting.tenant_id.is_(None),
                JobPosting.source != "recruiter",
                JobPosting.publication_status != "archived",
            )
            .with_for_update()
        )
    ).all()
    for job in jobs:
        await change_publication(
            db,
            job,
            None,
            "archive",
            JobPublicationChange(
                expected_version=job.version, note="Quelle hat das Inserat zurückgezogen."
            ),
        )
    await db.commit()
    return {"removed": len(jobs), "total": len(data.external_ids)}


# ── Single match ──────────────────────────────────────────────────────────────


@router.post(
    "/match",
    response_model=JobMatchResult,
    summary="Match-Score für einen einzelnen Job berechnen",
)
async def compute_job_match(
    data: JobMatchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JobMatchResult:
    from app.jobs.embeddings import embed_profile

    profile = await get_or_create_profile(db, current_user.id)
    profile_skills = [s.name for s in profile.skills]
    profile_embedding = await embed_profile(
        headline=profile.headline,
        summary=profile.summary,
        skills=profile_skills,
    )

    return await match_profile_to_job(
        db=db,
        profile_id=profile.id,
        job_id=data.job_id,
        profile_skills=profile_skills,
        profile_embedding=profile_embedding,
    )


# ── Recruiter job management ───────────────────────────────────────────────────


def _require_recruiter(user: User) -> User:
    if user.role not in {"recruiter", "admin"}:
        raise HTTPException(status_code=403, detail="Nur für Recruiter.")
    return user


async def _get_own_job(
    job_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
    *,
    lock: bool = False,
) -> JobPosting:
    query = select(JobPosting).where(JobPosting.id == job_id)
    if lock:
        query = query.with_for_update()
    job = await db.scalar(query.execution_options(populate_existing=True))
    if not job:
        raise HTTPException(status_code=404, detail="Job nicht gefunden.")
    if job.owner_id != current_user.id or job.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Kein Zugriff auf diesen Job.")
    return job


@router.post(
    "/recruiter",
    response_model=JobPostingRead,
    status_code=status.HTTP_201_CREATED,
    summary="Job-Inserat erstellen (Recruiter)",
)
async def recruiter_create_job(
    data: JobPostingCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
) -> JobPostingRead:
    _require_recruiter(current_user)
    job = await create_recruiter_job(db, data, owner_id=current_user.id)
    await enqueue_embedding(db, job.id, job.version, job.tenant_id)
    await db.commit()
    return JobPostingRead.model_validate(job)


@router.get(
    "/recruiter",
    response_model=dict,
    summary="Eigene Job-Inserate auflisten (Recruiter)",
)
async def recruiter_list_jobs(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    _require_recruiter(current_user)
    jobs, total = await list_my_jobs(db, current_user.id, page=page, page_size=page_size)
    return {
        "jobs": [JobPostingRead.model_validate(j) for j in jobs],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.patch(
    "/recruiter/{job_id}",
    response_model=JobPostingRead,
    summary="Job-Inserat bearbeiten (Recruiter)",
)
async def recruiter_update_job(
    job_id: uuid.UUID,
    data: JobPostingUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JobPostingRead:
    _require_recruiter(current_user)
    job = await _get_own_job(job_id, current_user, db, lock=True)
    updated = await update_recruiter_job(db, job, data)
    await enqueue_embedding(db, updated.id, updated.version, updated.tenant_id)
    await db.commit()
    return JobPostingRead.model_validate(updated)


@router.delete(
    "/recruiter/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Job-Inserat löschen (Recruiter)",
)
async def recruiter_delete_job(
    job_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    expected_version: int = Query(..., ge=1),
) -> None:
    _require_recruiter(current_user)
    job = await _get_own_job(job_id, current_user, db, lock=True)
    check_version(job, expected_version)
    await delete_recruiter_job(db, job)
    await db.commit()


@router.post(
    "/recruiter/{job_id}/publication/{action}",
    response_model=JobPostingRead,
    status_code=200,
    summary="Inserat veröffentlichen, zurückziehen oder archivieren",
)
async def recruiter_change_publication(
    job_id: uuid.UUID,
    action: str,
    data: JobPublicationChange,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JobPostingRead:
    _require_recruiter(current_user)
    if action not in {"publish", "withdraw", "archive"}:
        raise HTTPException(422, "Unbekannte Veröffentlichungsaktion.")
    job = await _get_own_job(job_id, current_user, db, lock=True)
    from typing import Literal, cast

    await change_publication(
        db, job, current_user.id, cast(Literal["publish", "withdraw", "archive"], action), data
    )
    if action == "publish" and job.embedding is None:
        await enqueue_embedding(db, job.id, job.version, job.tenant_id)
    await db.commit()
    return JobPostingRead.model_validate(job)


@router.get(
    "/recruiter/{job_id}/publication-events",
    response_model=list[JobPublicationEventRead],
    status_code=200,
    summary="Veröffentlichungsverlauf eines eigenen Inserats",
)
async def publication_events(
    job_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[JobPublicationEventRead]:
    _require_recruiter(current_user)
    await _get_own_job(job_id, current_user, db)
    rows = await db.scalars(
        select(JobPublicationEvent)
        .where(JobPublicationEvent.job_id == job_id)
        .order_by(JobPublicationEvent.version.desc())
        .limit(100)
    )
    return [JobPublicationEventRead.model_validate(row) for row in rows]


@router.get(
    "/recruiter/{job_id}/candidates",
    response_model=dict,
    summary="Kandidaten-Pipeline für ein Job-Inserat (Recruiter)",
)
async def recruiter_get_candidates(
    job_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    _require_recruiter(current_user)
    job = await _get_own_job(job_id, current_user, db)
    candidates, total = await get_candidates_for_job(db, job, page=page, page_size=page_size)
    return {
        "candidates": [c.model_dump() for c in candidates],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get(
    "/recruiter/{job_id}/applications",
    response_model=dict,
    summary="Bewerbungen für ein Job-Inserat (Recruiter)",
)
async def recruiter_get_applications(
    job_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    _require_recruiter(current_user)
    job = await _get_own_job(job_id, current_user, db)
    apps, total = await get_applications_for_job(db, job.id, page=page, page_size=page_size)
    return {
        "applications": [a.model_dump() for a in apps],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get(
    "/recruiter/applications",
    response_model=dict,
    summary="Alle Bewerbungen für alle eigenen Jobs (Recruiter-Übersicht)",
)
async def recruiter_get_all_applications(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    application_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    from sqlalchemy import func as _func
    from sqlalchemy.orm import selectinload

    from app.applications.models import Application, ApplicationStatus
    from app.jobs.models import JobPosting as _JobPosting

    _require_recruiter(current_user)

    from app.companies.workspace_access import job_scope

    # Shared recruiting work uses the same scope as interviews and person records.
    jobs_result = await db.execute(
        select(_JobPosting.id, _JobPosting.title).where(job_scope(current_user))
    )
    job_rows = jobs_result.all()
    if not job_rows:
        return {"applications": [], "total": 0, "page": page, "page_size": page_size}

    job_ids = [r.id for r in job_rows]
    job_title_map = {r.id: r.title for r in job_rows}

    stmt = (
        select(Application)
        .where(Application.job_id.in_(job_ids))
        .options(selectinload(Application.history))
        .order_by(Application.created_at.desc())
    )
    if status_filter:
        with suppress(ValueError):
            stmt = stmt.where(Application.status == ApplicationStatus(status_filter))

    if application_id is not None:
        stmt = stmt.where(Application.id == application_id)

    count_stmt = select(_func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    apps_result = await db.execute(stmt)
    apps = apps_result.scalars().all()

    from app.profiles.models import CandidateProfile
    from app.users.models import User as UserModel

    # Build response with candidate info + job title
    response_apps = []
    for app in apps:
        # Get candidate name
        user_result = await db.execute(select(UserModel).where(UserModel.id == app.user_id))
        user = user_result.scalar_one_or_none()
        profile_result = await db.execute(
            select(CandidateProfile).where(CandidateProfile.user_id == app.user_id)
        )
        profile = profile_result.scalar_one_or_none()

        response_apps.append(
            {
                "id": str(app.id),
                "user_id": str(app.user_id),
                "job_id": str(app.job_id) if app.job_id else None,
                "job_title": (
                    job_title_map.get(app.job_id, app.position) if app.job_id else app.position
                ),
                "candidate_name": user.full_name if user else None,
                "candidate_headline": profile.headline if profile else None,
                "candidate_location": profile.location if profile else None,
                "status": app.status.value,
                "applied_at": app.applied_at.isoformat() if app.applied_at else None,
                "created_at": app.created_at.isoformat(),
                "notes": app.notes,
            }
        )

    return {
        "applications": response_apps,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get(
    "/recruiter/applications/export",
    summary="Alle Bewerbungen als CSV exportieren (Recruiter)",
    response_class=Response,
    tags=["export"],
)
async def recruiter_export_applications(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: str | None = Query(None, alias="status"),
) -> Response:
    import csv
    import io

    from app.applications.models import Application, ApplicationStatus
    from app.jobs.models import JobPosting as _JobPosting
    from app.profiles.models import CandidateProfile
    from app.users.models import User as UserModel
    from app.utils.csv import literal_cell

    _require_recruiter(current_user)

    jobs_result = await db.execute(
        select(_JobPosting.id, _JobPosting.title).where(
            _JobPosting.owner_id == current_user.id,
            _JobPosting.tenant_id == current_user.tenant_id,
        )
    )
    job_rows = jobs_result.all()
    if not job_rows:
        return Response(
            content="",
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=bewerbungen.csv"},
        )

    job_ids = [r.id for r in job_rows]
    job_title_map = {r.id: r.title for r in job_rows}

    stmt = (
        select(Application)
        .where(Application.job_id.in_(job_ids))
        .order_by(Application.created_at.desc())
    )
    if status_filter:
        with contextlib.suppress(ValueError):
            stmt = stmt.where(Application.status == ApplicationStatus(status_filter))

    apps_result = await db.execute(stmt)
    apps = apps_result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["Name", "Headline", "Standort", "E-Mail", "Stelle", "Status", "Datum", "Notizen"]
    )

    for app in apps:
        user_result = await db.execute(select(UserModel).where(UserModel.id == app.user_id))
        user = user_result.scalar_one_or_none()
        profile_result = await db.execute(
            select(CandidateProfile).where(CandidateProfile.user_id == app.user_id)
        )
        profile = profile_result.scalar_one_or_none()

        writer.writerow(
            [
                literal_cell(value)
                for value in [
                    user.full_name if user else "",
                    profile.headline if profile else "",
                    profile.location if profile else "",
                    user.email if user else "",
                    job_title_map.get(app.job_id, app.position) if app.job_id else app.position,
                    app.status.value,
                    (
                        (app.applied_at or app.created_at).strftime("%Y-%m-%d")
                        if (app.applied_at or app.created_at)
                        else ""
                    ),
                    app.notes or "",
                ]
            ]
        )

    csv_content = output.getvalue()
    return Response(
        content=csv_content.encode("utf-8-sig"),  # BOM for Excel compatibility
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": "attachment; filename=bewerbungen.csv"},
    )


@router.patch(
    "/recruiter/{job_id}/applications/{app_id}",
    response_model=dict,
    summary="Bewerbungsstatus durch Recruiter aktualisieren",
)
async def recruiter_update_application(
    job_id: uuid.UUID,
    app_id: uuid.UUID,
    data: RecruiterApplicationUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    from app.applications.models import Application, ApplicationStatus

    _require_recruiter(current_user)
    from app.pipeline.access import require_application

    await require_application(db, app_id, current_user)

    # Validate new status
    try:
        ApplicationStatus(data.status)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Ungültiger Status: {data.status}") from None

    # Load the application
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.job_id == job_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Bewerbung nicht gefunden.")

    updated = await update_application_as_recruiter(db, app, data.status, data.note)
    await db.commit()
    return {"id": str(updated.id), "status": updated.status.value}


# ── Bulk application status update ────────────────────────────────────────────


class BulkApplicationUpdateRequest(BaseModel):
    application_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    status: str


@router.patch(
    "/recruiter/applications/bulk",
    response_model=dict,
    summary="Mehrere Bewerbungen gleichzeitig aktualisieren (Recruiter)",
)
async def recruiter_bulk_update_applications(
    data: BulkApplicationUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    from app.applications.models import Application, ApplicationStatus
    from app.jobs.models import JobPosting as _JobPosting

    _require_recruiter(current_user)

    try:
        ApplicationStatus(data.status)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Ungültiger Status: {data.status}") from None

    from app.companies.workspace_access import job_scope

    # Use the same company scope as the individual application view.
    jobs_result = await db.execute(select(_JobPosting.id).where(job_scope(current_user)))
    own_job_ids = [r.id for r in jobs_result.all()]

    apps_result = await db.execute(
        select(Application).where(
            Application.id.in_(data.application_ids),
            Application.job_id.in_(own_job_ids),
        )
    )
    apps = apps_result.scalars().all()

    if len(apps) != len(set(data.application_ids)):
        raise HTTPException(404, "Mindestens eine Bewerbung ist nicht im Arbeitsbereich verfügbar.")

    updated_count = 0
    for app in apps:
        await update_application_as_recruiter(db, app, data.status, None)
        updated_count += 1

    await db.commit()
    return {"updated": updated_count, "requested": len(data.application_ids)}


# ── Candidate: apply to a job ──────────────────────────────────────────────────


class ApplyRequest(BaseModel):
    notes: str | None = None


@router.post(
    "/{job_id}/apply",
    status_code=status.HTTP_201_CREATED,
    summary="Direkt auf ein Job-Inserat bewerben",
)
async def apply_to_job_endpoint(
    job_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    data: ApplyRequest | None = None,
) -> dict[str, Any]:
    job = await require_public_job(db, job_id, lock=True)
    if not job:
        raise HTTPException(status_code=404, detail="Job nicht gefunden.")

    app = await apply_to_job(db, current_user.id, job)
    if data and data.notes:
        app.notes = data.notes
    await db.commit()

    return {
        "application_id": str(app.id),
        "job_id": str(job_id),
        "status": app.status.value,
        "message": f"Erfolgreich auf '{job.title}' beworben.",
    }


# ── Recruiter Dashboard Stats ─────────────────────────────────────────────────


@router.get(
    "/recruiter/stats",
    response_model=dict,
    summary="Aggregierte KPI-Statistiken für Recruiter-Dashboard",
)
async def recruiter_dashboard_stats(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    _require_recruiter(current_user)

    import datetime

    from sqlalchemy import func

    from app.applications.models import Application
    from app.interviews.models import InterviewSchedule
    from app.jobs.models import JobPosting

    # Count recruiter's jobs
    job_count = (
        await db.execute(
            select(func.count())
            .select_from(JobPosting)
            .where(
                JobPosting.owner_id == current_user.id,
                JobPosting.tenant_id == current_user.tenant_id,
            )
        )
    ).scalar_one()

    # All job IDs owned by recruiter
    job_ids_result = await db.execute(
        select(JobPosting.id).where(
            JobPosting.owner_id == current_user.id, JobPosting.tenant_id == current_user.tenant_id
        )
    )
    job_ids = [r[0] for r in job_ids_result]

    if not job_ids:
        return {
            "total_jobs": 0,
            "total_applications": 0,
            "applications_by_status": {},
            "interviews_this_week": 0,
            "new_applications_today": 0,
        }

    # Total applications across all jobs
    total_apps = (
        await db.execute(
            select(func.count()).select_from(Application).where(Application.job_id.in_(job_ids))
        )
    ).scalar_one()

    # Applications by status
    status_rows = (
        await db.execute(
            select(Application.status, func.count().label("cnt"))
            .where(Application.job_id.in_(job_ids))
            .group_by(Application.status)
        )
    ).all()
    by_status = {str(r.status.value): r.cnt for r in status_rows}

    # New applications today
    today_start = datetime.datetime.now(datetime.UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    new_today = (
        await db.execute(
            select(func.count())
            .select_from(Application)
            .where(
                Application.job_id.in_(job_ids),
                Application.created_at >= today_start,
            )
        )
    ).scalar_one()

    # Interviews this week
    week_start = today_start - datetime.timedelta(days=today_start.weekday())
    week_end = week_start + datetime.timedelta(days=7)
    interviews_this_week = (
        await db.execute(
            select(func.count())
            .select_from(InterviewSchedule)
            .join(Application, Application.id == InterviewSchedule.application_id)
            .where(
                Application.job_id.in_(job_ids),
                InterviewSchedule.scheduled_at >= week_start,
                InterviewSchedule.scheduled_at < week_end,
                InterviewSchedule.status.in_(["proposed", "confirmed"]),
            )
        )
    ).scalar_one()

    return {
        "total_jobs": job_count,
        "total_applications": total_apps,
        "applications_by_status": by_status,
        "interviews_this_week": interviews_this_week,
        "new_applications_today": new_today,
    }


@router.get(
    "/recruiter/candidates",
    response_model=dict,
    summary="Kandidaten-Suche (Recruiter) – Skills, Ort, Freitext",
)
async def recruiter_search_candidates(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    query: str | None = Query(None, description="Freitext (Name, Headline, Summary)"),
    skills: list[str] = Query(default=[], description="Skill-Filter (mehrere erlaubt)"),
    location: str | None = Query(None),
    available_only: bool = Query(False, description="Nur Pool-Kandidaten (Zeitarbeit)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    from sqlalchemy import func as _func
    from sqlalchemy import or_

    from app.profiles.models import CandidateProfile
    from app.profiles.models import Skill as _Skill
    from app.users.models import User as UserModel

    _require_recruiter(current_user)

    from app.jobs.access import candidate_visibility

    stmt = (
        select(CandidateProfile, UserModel)
        .join(UserModel, UserModel.id == CandidateProfile.user_id)
        .where(candidate_visibility(current_user.id, current_user.tenant_id))
    )

    # Freitext filter
    if query:
        q = f"%{query.lower()}%"
        stmt = stmt.where(
            or_(
                _func.lower(UserModel.full_name).like(q),
                _func.lower(CandidateProfile.headline).like(q),
                _func.lower(CandidateProfile.summary).like(q),
                _func.lower(CandidateProfile.location).like(q),
            )
        )

    # Location filter
    if location:
        stmt = stmt.where(_func.lower(CandidateProfile.location).like(f"%{location.lower()}%"))

    # Skills filter: profile must have ALL requested skills
    if skills:
        for skill in skills:
            stmt = stmt.where(
                CandidateProfile.id.in_(
                    select(_Skill.profile_id).where(_func.lower(_Skill.name) == skill.lower())
                )
            )

    # Pool filter
    if available_only:
        from app.zeitarbeit.models import TempWorkerAvailability as WorkerAvailability

        stmt = stmt.where(
            CandidateProfile.user_id.in_(
                select(WorkerAvailability.user_id).where(
                    WorkerAvailability.is_in_pool.is_(True)
                )  # noqa: E712
            )
        )

    # Count
    count_stmt = select(_func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        stmt.order_by(CandidateProfile.completeness_score.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).all()

    candidates = []
    for profile, user in rows:
        candidates.append(
            {
                "user_id": str(user.id),
                "profile_id": str(profile.id),
                "full_name": user.full_name,
                "headline": profile.headline,
                "location": profile.location,
                "completeness_score": profile.completeness_score,
            }
        )

    return {"candidates": candidates, "total": total, "page": page, "page_size": page_size}


@router.get(
    "/recruiter/candidates/{user_id}/profile",
    response_model=dict,
    summary="Kandidaten-Profil für Recruiter-Ansicht",
)
async def recruiter_candidate_profile(
    user_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Return a candidate's full profile for recruiter review."""
    _require_recruiter(current_user)

    from sqlalchemy.orm import selectinload

    from app.jobs.access import candidate_visibility
    from app.profiles.models import CandidateProfile
    from app.users.models import User as UserModel

    user_row = await db.execute(
        select(UserModel).where(
            UserModel.id == user_id,
            candidate_visibility(current_user.id, current_user.tenant_id),
        )
    )
    candidate = user_row.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Kandidat nicht gefunden.")

    profile_row = await db.execute(
        select(CandidateProfile)
        .options(
            selectinload(CandidateProfile.work_experiences),
            selectinload(CandidateProfile.educations),
            selectinload(CandidateProfile.skills),
        )
        .where(CandidateProfile.user_id == user_id)
    )
    profile = profile_row.scalar_one_or_none()

    return {
        "user_id": str(candidate.id),
        "full_name": candidate.full_name,
        "email": candidate.email,
        "headline": profile.headline if profile else None,
        "summary": profile.summary if profile else None,
        "location": profile.location if profile else None,
        "phone": profile.phone if profile else None,
        "linkedin_url": profile.linkedin_url if profile else None,
        "completeness_score": profile.completeness_score if profile else 0,
        "work_experiences": [
            {
                "company": e.company,
                "title": e.title,
                "start_date": str(e.start_date) if e.start_date else None,
                "end_date": str(e.end_date) if e.end_date else None,
                "is_current": e.is_current,
                "description": e.description,
            }
            for e in (profile.work_experiences if profile else [])
        ],
        "educations": [
            {
                "institution": e.institution,
                "degree": e.degree,
                "field_of_study": e.field_of_study,
                "start_date": str(e.start_date) if e.start_date else None,
                "end_date": str(e.end_date) if e.end_date else None,
            }
            for e in (profile.educations if profile else [])
        ],
        "skills": [
            {"name": s.name, "level": s.level, "category": s.category}
            for s in (profile.skills if profile else [])
        ],
    }


# ── LinkedIn Content-Kit ──────────────────────────────────────────────────────


class LinkedInShareResponse(BaseModel):
    text: str
    post_type: str
    ai_generated: bool
    disclaimer: str


@router.post(
    "/recruiter/jobs/{job_id}/share/linkedin",
    response_model=LinkedInShareResponse,
    summary="KI-LinkedIn-Post für Stellenausschreibung generieren",
)
async def generate_job_linkedin_post(
    job_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LinkedInShareResponse:
    _require_recruiter(current_user)
    tid = str(current_user.tenant_id) if current_user.tenant_id else None
    if not await check_module_enabled(tid, "ai_linkedin_post"):
        raise HTTPException(
            status_code=403,
            detail="Modul 'ai_linkedin_post' ist für Ihren Plan nicht freigeschaltet.",
        )
    job = await _get_own_job(job_id, current_user, db)
    from app.ai.generators.linkedin_post import generate_job_post

    result = await generate_job_post(
        title=job.title,
        company=job.company,
        location=job.location,
        description=job.description or "",
        required_skills=job.required_skills or [],
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        is_remote=job.is_remote or False,
        employment_type=job.employment_type,
    )
    await track_ai_usage(tid, "ai_linkedin_post")
    return LinkedInShareResponse(
        text=result.text,
        post_type=result.post_type,
        ai_generated=result.ai_generated,
        disclaimer=result.disclaimer,
    )


class PlacementShareRequest(BaseModel):
    position: str
    company: str
    category: str | None = None


@router.post(
    "/recruiter/placements/share/linkedin",
    response_model=LinkedInShareResponse,
    summary="KI-LinkedIn-Post für erfolgreiche Vermittlung generieren",
)
async def generate_placement_linkedin_post(
    body: PlacementShareRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LinkedInShareResponse:
    _require_recruiter(current_user)
    tid = str(current_user.tenant_id) if current_user.tenant_id else None
    if not await check_module_enabled(tid, "ai_linkedin_post"):
        raise HTTPException(
            status_code=403,
            detail="Modul 'ai_linkedin_post' ist für Ihren Plan nicht freigeschaltet.",
        )
    from app.ai.generators.linkedin_post import generate_placement_post

    result = await generate_placement_post(
        position=body.position,
        company=body.company,
        category=body.category,
    )
    await track_ai_usage(tid, "ai_linkedin_post")
    return LinkedInShareResponse(
        text=result.text,
        post_type=result.post_type,
        ai_generated=result.ai_generated,
        disclaimer=result.disclaimer,
    )


# ── Market Stats ───────────────────────────────────────────────────────────────


@router.get(
    "/market/stats",
    response_model=MarketStats,
    summary="Aggregierte Marktstatistiken (Top-Skills, Gehalt, Kategorien)",
)
async def market_stats(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MarketStats:
    return await get_market_stats(db)


# ── Saved jobs (bookmarks) ────────────────────────────────────────────────────


@router.post(
    "/{job_id}/save",
    status_code=status.HTTP_201_CREATED,
    summary="Job merken (Lesezeichen setzen)",
)
async def save_job(
    job_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.jobs.models import SavedJob

    job = await require_public_job(db, job_id, lock=True)
    if not job:
        raise HTTPException(status_code=404, detail="Job nicht gefunden.")

    # Upsert – ignore duplicates
    stmt = (
        pg_insert(SavedJob)
        .values(
            id=uuid.uuid4(),
            user_id=current_user.id,
            job_id=job_id,
        )
        .on_conflict_do_nothing(constraint="uq_saved_jobs_user_job")
    )
    await db.execute(stmt)
    await db.commit()
    return {"job_id": str(job_id), "saved": True}


@router.delete(
    "/{job_id}/save",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Job aus Merkliste entfernen",
)
async def unsave_job(
    job_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    from app.jobs.models import SavedJob

    result = await db.execute(
        select(SavedJob).where(
            SavedJob.user_id == current_user.id,
            SavedJob.job_id == job_id,
        )
    )
    row = result.scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()


@router.get(
    "/saved",
    response_model=list[JobPostingRead],
    summary="Gemerkte Jobs abrufen",
)
async def list_saved_jobs(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Any]:
    from app.jobs.models import JobPosting, SavedJob

    result = await db.execute(
        select(JobPosting)
        .join(SavedJob, SavedJob.job_id == JobPosting.id)
        .where(SavedJob.user_id == current_user.id, public_job_condition())
        .order_by(SavedJob.created_at.desc())
    )
    return list(result.scalars().all())


@router.get(
    "/saved/ids",
    response_model=list[str],
    summary="IDs aller gemerkten Jobs abrufen",
)
async def list_saved_job_ids(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Any]:
    from app.jobs.models import SavedJob

    result = await db.execute(
        select(SavedJob.job_id)
        .join(JobPosting, JobPosting.id == SavedJob.job_id)
        .where(SavedJob.user_id == current_user.id, public_job_condition())
    )
    return [str(row) for row in result.scalars().all()]


# ── Recruiter Interviews Overview ─────────────────────────────────────────────


@router.get(
    "/recruiter/interviews",
    response_model=dict,
    summary="Alle Interview-Termine für Recruiter-Jobs",
)
async def recruiter_list_interviews(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    interview_status: str | None = Query(None, description="proposed|confirmed|declined|cancelled"),
    upcoming_only: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """Return all interview schedules across all jobs owned by this recruiter."""
    from datetime import datetime

    from sqlalchemy import func as _func

    from app.applications.models import Application
    from app.interviews.models import InterviewSchedule
    from app.users.models import User as UserModel

    _require_recruiter(current_user)

    # Base join: interview → application → job (owned by recruiter)
    base_q = (
        select(InterviewSchedule, Application, JobPosting, UserModel)
        .join(Application, InterviewSchedule.application_id == Application.id)
        .join(JobPosting, Application.job_id == JobPosting.id)
        .join(UserModel, Application.user_id == UserModel.id)
        .where(
            JobPosting.owner_id == current_user.id, JobPosting.tenant_id == current_user.tenant_id
        )
    )

    if interview_status:
        base_q = base_q.where(InterviewSchedule.status == interview_status)

    if upcoming_only:
        now = datetime.now(UTC)
        base_q = base_q.where(InterviewSchedule.scheduled_at >= now)

    # Count
    count_q = select(_func.count()).select_from(base_q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    # Fetch page
    rows_q = (
        base_q.order_by(InterviewSchedule.scheduled_at.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(rows_q)).all()

    interviews = []
    for iv, _app, job, cand_user in rows:
        interviews.append(
            {
                "id": str(iv.id),
                "application_id": str(iv.application_id),
                "job_id": str(job.id),
                "job_title": job.title,
                "candidate_user_id": str(cand_user.id),
                "candidate_name": cand_user.full_name,
                "candidate_email": cand_user.email,
                "scheduled_at": iv.scheduled_at.isoformat(),
                "status": iv.status,
                "meeting_url": iv.meeting_url,
                "notes": iv.notes,
                "created_at": iv.created_at.isoformat(),
            }
        )

    return {"interviews": interviews, "total": total, "page": page, "page_size": page_size}


# ── Recruiter Analytics ────────────────────────────────────────────────────────


@router.get(
    "/recruiter/analytics",
    response_model=dict,
    summary="Erweiterte Recruiting-Analytics für den Recruiter",
)
async def recruiter_analytics(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = Query(30, ge=7, le=90, description="Zeitraum in Tagen"),
) -> dict[str, Any]:
    """Daily application counts, stage funnel, and top jobs by applications."""
    import datetime

    from sqlalchemy import Date, cast
    from sqlalchemy import func as _func

    from app.applications.models import Application
    from app.jobs.models import JobPosting as _JobPosting

    _require_recruiter(current_user)

    # Get all owned job IDs
    job_ids_result = await db.execute(
        select(_JobPosting.id, _JobPosting.title).where(
            _JobPosting.owner_id == current_user.id,
            _JobPosting.tenant_id == current_user.tenant_id,
        )
    )
    job_rows = job_ids_result.all()
    if not job_rows:
        return {
            "daily_applications": [],
            "funnel": {},
            "top_jobs": [],
            "days": days,
        }

    job_ids = [r.id for r in job_rows]
    job_title_map = {r.id: r.title for r in job_rows}

    since = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)

    # Daily application counts
    daily_result = await db.execute(
        select(
            cast(Application.created_at, Date).label("day"),
            _func.count().label("cnt"),
        )
        .where(
            Application.job_id.in_(job_ids),
            Application.created_at >= since,
        )
        .group_by(cast(Application.created_at, Date))
        .order_by(cast(Application.created_at, Date))
    )
    daily_rows = daily_result.all()

    # Fill in zero-days
    from datetime import timedelta

    start_date = since.date()
    end_date = datetime.datetime.now(datetime.UTC).date()
    daily_map = {r.day: r.cnt for r in daily_rows}
    daily_applications = []
    d = start_date
    while d <= end_date:
        daily_applications.append({"date": d.isoformat(), "count": daily_map.get(d, 0)})
        d += timedelta(days=1)

    # Funnel: count by status (ordered)
    status_result = await db.execute(
        select(Application.status, _func.count().label("cnt"))
        .where(Application.job_id.in_(job_ids))
        .group_by(Application.status)
    )
    funnel = {r.status.value: r.cnt for r in status_result.all()}

    # Top jobs by application count
    top_jobs_result = await db.execute(
        select(Application.job_id, _func.count().label("cnt"))
        .where(Application.job_id.in_(job_ids))
        .group_by(Application.job_id)
        .order_by(_func.count().desc())
        .limit(10)
    )
    top_jobs = [
        {"job_id": str(r.job_id), "title": job_title_map.get(r.job_id, "—"), "count": r.cnt}
        for r in top_jobs_result.all()
    ]

    return {
        "daily_applications": daily_applications,
        "funnel": funnel,
        "top_jobs": top_jobs,
        "days": days,
    }


# ── Job Alerts (Sprint 2.0) ───────────────────────────────────────────────────


@router.get(
    "/alerts",
    response_model=list[JobAlertRead],
    summary="Eigene Job-Alarme auflisten",
)
async def list_job_alerts(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Any]:
    from app.jobs.models import JobAlert

    result = await db.execute(
        select(JobAlert)
        .where(JobAlert.user_id == current_user.id)
        .order_by(JobAlert.created_at.desc())
    )
    return list(result.scalars().all())


@router.post(
    "/alerts",
    response_model=JobAlertRead,
    status_code=status.HTTP_201_CREATED,
    summary="Neuen Job-Alarm anlegen",
)
async def create_job_alert(
    data: JobAlertCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> object:
    from app.jobs.models import JobAlert

    alert = JobAlert(
        user_id=current_user.id,
        keywords=data.keywords,
        location=data.location,
        remote_only=data.remote_only,
        min_salary=data.min_salary,
        category=data.category,
        min_score=data.min_score,
    )
    db.add(alert)
    await db.flush()
    await db.refresh(alert)
    return alert


@router.patch(
    "/alerts/{alert_id}",
    response_model=JobAlertRead,
    summary="Job-Alarm aktivieren / deaktivieren",
)
async def toggle_job_alert(
    alert_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> object:
    from app.jobs.models import JobAlert

    result = await db.execute(
        select(JobAlert).where(JobAlert.id == alert_id, JobAlert.user_id == current_user.id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Job-Alarm nicht gefunden.")
    alert.is_active = not alert.is_active
    await db.flush()
    await db.refresh(alert)
    return alert


@router.delete(
    "/alerts/{alert_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Job-Alarm löschen",
)
async def delete_job_alert(
    alert_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    from app.jobs.models import JobAlert

    result = await db.execute(
        select(JobAlert).where(JobAlert.id == alert_id, JobAlert.user_id == current_user.id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Job-Alarm nicht gefunden.")
    await db.delete(alert)
    await db.flush()


@router.get(
    "/recruiter/{job_id}",
    response_model=JobPostingRead,
    status_code=200,
    summary="Eigenes Job-Inserat abrufen",
)
async def recruiter_get_job(
    job_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JobPostingRead:
    _require_recruiter(current_user)
    return JobPostingRead.model_validate(await _get_own_job(job_id, current_user, db))
