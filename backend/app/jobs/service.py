"""Job service – CRUD + matching logic."""

from __future__ import annotations

import uuid
from datetime import UTC
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from sqlalchemy import ColumnElement, and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.access import candidate_visibility
from app.jobs.models import JobMatchScore, JobPosting
from app.jobs.publication import (
    check_version,
    public_job_condition,
    record_change,
    require_public_job,
)
from app.jobs.schemas import (
    CandidateMatchRead,
    JobFilter,
    JobMatchResult,
    JobPostingCreate,
    JobPostingRead,
    JobPostingUpdate,
    LearningPath,
    MarketStats,
    ProfileGapAnalysis,
    SalaryStat,
    SkillGap,
)

if TYPE_CHECKING:
    from app.applications.models import Application
    from app.jobs.schemas import RecruiterApplicationRead

# ── Category classification ───────────────────────────────────────────────────

_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    (
        "IT/Software",
        [
            "developer",
            "engineer",
            "software",
            "backend",
            "frontend",
            "fullstack",
            "devops",
            "cloud",
            "architect",
            "ios",
            "android",
            "python",
            "java ",
            "javascript",
            "typescript",
            "react",
            "golang",
            "rust ",
            "sre",
            "platform",
            "infrastructure",
            "kubernetes",
            "docker",
            "microservice",
            "api ",
        ],
    ),
    (
        "Data & Analytics",
        [
            "data scientist",
            "data analyst",
            "data engineer",
            "machine learning",
            "deep learning",
            " ai ",
            "analytics",
            "business intelligence",
            " bi ",
            "statistik",
            "mlops",
            "nlp",
            "llm",
            "datenbank",
        ],
    ),
    (
        "Design/UX",
        [
            "designer",
            " ux",
            " ui ",
            "graphic",
            "creative",
            "gestaltung",
            "motion design",
            "product design",
            "visual",
        ],
    ),
    (
        "Marketing",
        [
            "marketing",
            " seo",
            "content",
            "social media",
            "brand",
            " pr ",
            "kommunikation",
            "growth",
            "performance marketing",
            "campaign",
            "redakteur",
        ],
    ),
    (
        "Sales/Vertrieb",
        [
            "sales",
            "vertrieb",
            "account manager",
            "key account",
            "business development",
            " bdr",
            " sdr",
            "außendienst",
        ],
    ),
    (
        "Finance",
        [
            "finance",
            "accounting",
            "controller",
            "buchhalter",
            "steuer",
            "audit",
            "treasury",
            "finanzanalyst",
            "kreditrisiko",
        ],
    ),
    (
        "HR/People",
        [
            " hr ",
            "recruiter",
            "talent acquisition",
            "people & culture",
            "personalreferent",
            "personalleiter",
        ],
    ),
    (
        "Operations",
        [
            "operations",
            "logistics",
            "supply chain",
            "einkauf",
            "procurement",
            "project manager",
            "projektleiter",
            "scrum master",
            "agile coach",
        ],
    ),
    (
        "Management",
        [
            "head of",
            "director",
            " vp ",
            " cto",
            " cpo",
            " coo",
            " ceo",
            "leiter ",
            "geschäftsführer",
        ],
    ),
    (
        "Customer Success",
        [
            "customer success",
            "customer support",
            "helpdesk",
            "service desk",
            "kundendienst",
            "kundenberatung",
            "kundenbetreuer",
        ],
    ),
    (
        "Engineering",
        [
            "ingenieur",
            "techniker",
            "mechanical",
            "electrical",
            "maschinenbau",
            "elektrotechnik",
            "civil",
            "bauingenieur",
            "verfahrenstechnik",
        ],
    ),
]


def classify_category(title: str, description: str | None = None) -> str:
    """Rule-based job category classifier. Fast, no ML needed."""
    text = (title + " " + (description or "")[:300]).lower()
    for category, keywords in _CATEGORY_RULES:
        if any(kw in text for kw in keywords):
            return category
    return "Sonstige"


# ── CRUD ─────────────────────────────────────────────────────────────────────


def _normalize_required_skills(skills: list[str]) -> list[str]:
    """Store skills as plain comma-separated values, without list prefixes."""
    return [cleaned for skill in skills if (cleaned := skill.strip().lstrip("-–—").strip())]


async def create_job(db: AsyncSession, data: JobPostingCreate) -> JobPosting | None:
    """Insert a job posting. Returns None if external_id already exists (skip)."""
    if data.external_id:
        result = await db.execute(
            select(JobPosting).where(JobPosting.external_id == data.external_id)
        )
        if result.scalar_one_or_none() is not None:
            return None

    job_data = data.model_dump(exclude_none=True)
    job_data["required_skills"] = _normalize_required_skills(data.required_skills)
    job_data["category"] = classify_category(data.title, data.description)
    job = JobPosting(**job_data)
    db.add(job)
    await db.flush()
    return job


async def get_job_by_id(db: AsyncSession, job_id: uuid.UUID) -> JobPosting | None:
    result = await db.execute(select(JobPosting).where(JobPosting.id == job_id))
    return result.scalar_one_or_none()


async def list_jobs(
    db: AsyncSession,
    filters: JobFilter,
) -> tuple[list[JobPosting], int]:
    """Return (jobs, total_count) with filters applied."""
    q = select(JobPosting)
    count_q = select(func.count()).select_from(JobPosting)

    conditions = _build_conditions(filters)
    for cond in conditions:
        q = q.where(cond)
        count_q = count_q.where(cond)

    total = (await db.execute(count_q)).scalar_one()
    offset = (filters.page - 1) * filters.page_size
    q = q.order_by(JobPosting.created_at.desc()).offset(offset).limit(filters.page_size)
    jobs = (await db.execute(q)).scalars().all()
    return list(jobs), total


def _build_conditions(filters: JobFilter) -> list[Any]:
    conditions: list[ColumnElement[bool]] = [public_job_condition()]
    if filters.remote_only:
        conditions.append(JobPosting.is_remote.is_(True))
    if filters.min_salary is not None:
        conditions.append(JobPosting.salary_max >= filters.min_salary)
    if filters.location:
        conditions.append(JobPosting.location.ilike(f"%{filters.location}%"))
    if filters.category:
        conditions.append(JobPosting.category == filters.category)
    if filters.skills:
        # GIN index: jobs that require ANY of the given skills
        conditions.append(JobPosting.required_skills.overlap(filters.skills))
    if filters.text_search:
        # Each word must appear somewhere in title or description (trigram index on title)
        from sqlalchemy import or_

        for word in filters.text_search.split()[:5]:
            conditions.append(
                or_(
                    JobPosting.title.ilike(f"%{word}%"),
                    JobPosting.description.ilike(f"%{word}%"),
                )
            )
    return conditions


# ── Matching ──────────────────────────────────────────────────────────────────


def _skill_overlap(job_skills: list[str], profile_skills: list[str]) -> float:
    if not job_skills:
        return 1.0
    job_lower = {s.lower() for s in job_skills}
    profile_lower = {s.lower() for s in profile_skills}
    matched = job_lower & profile_lower
    return len(matched) / len(job_lower)


def compute_match_score(
    vector_sim: float,
    skill_ov: float,
    profile_skills: list[str],
    job_skills: list[str],
) -> tuple[float, dict[str, Any]]:
    """60% vector similarity + 40% skill overlap → score 0–100."""
    vec_norm = max(0.0, min(1.0, (vector_sim + 1.0) / 2.0))
    score = (vec_norm * 0.6 + skill_ov * 0.4) * 100.0

    matched = list({s.lower() for s in job_skills} & {s.lower() for s in profile_skills})
    missing = list({s.lower() for s in job_skills} - {s.lower() for s in profile_skills})

    explanation = {
        "vector_similarity_raw": round(vector_sim, 4),
        "vector_contribution": round(vec_norm * 0.6 * 100, 1),
        "skill_overlap_pct": round(skill_ov * 100, 1),
        "skill_contribution": round(skill_ov * 0.4 * 100, 1),
        "matched_skills": matched[:10],
        "missing_skills": missing[:10],
    }
    return round(score, 1), explanation


async def match_profile_to_job(
    db: AsyncSession,
    profile_id: uuid.UUID,
    job_id: uuid.UUID,
    profile_skills: list[str],
    profile_embedding: list[float],
) -> JobMatchResult:
    from app.jobs.embeddings import cosine_similarity

    job = await require_public_job(db, job_id)
    if job is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Job nicht gefunden.")

    if job.embedding is None:
        from app.jobs.embeddings import embed_job

        job.embedding = await embed_job(job.title, job.description)
        await db.flush()

    vec_sim = cosine_similarity(profile_embedding, job.embedding)
    skill_ov = _skill_overlap(list(job.required_skills or []), profile_skills)
    score, explanation = compute_match_score(
        vec_sim, skill_ov, profile_skills, list(job.required_skills or [])
    )

    # Upsert cache
    existing = await db.execute(
        select(JobMatchScore).where(
            JobMatchScore.profile_id == profile_id,
            JobMatchScore.job_id == job_id,
        )
    )
    cache = existing.scalar_one_or_none()
    if cache:
        cache.score = score
        cache.vector_similarity = vec_sim
        cache.skill_overlap = skill_ov
        cache.explanation = explanation
    else:
        db.add(
            JobMatchScore(
                profile_id=profile_id,
                job_id=job_id,
                score=score,
                vector_similarity=vec_sim,
                skill_overlap=skill_ov,
                explanation=explanation,
            )
        )
    await db.flush()

    return JobMatchResult(
        job=JobPostingRead.model_validate(job),
        score=score,
        vector_similarity=vec_sim,
        skill_overlap=skill_ov,
        explanation=explanation,
    )


async def get_recommended_jobs(
    db: AsyncSession,
    profile_id: uuid.UUID,
    profile_skills: list[str],
    profile_embedding: list[float],
    filters: JobFilter,
) -> tuple[list[JobMatchResult], int]:
    """
    ANN search via pgvector HNSW index, then re-rank with skill overlap.

    Replaces the old Python-loop approach. One SQL query does all the heavy
    lifting; Python only applies the composite score on the already-small result set.
    """
    # Detect zero-vector fallback (embedding model unavailable)
    zero_vec = not any(profile_embedding)

    base_conditions = _build_conditions(filters)
    if not zero_vec:
        base_conditions.append(JobPosting.embedding.is_not(None))

    # ── Count total for pagination ────────────────────────────────────────────
    count_q = select(func.count()).select_from(JobPosting).where(*base_conditions)
    total = (await db.execute(count_q)).scalar_one()

    if total == 0:
        return [], 0

    offset = (filters.page - 1) * filters.page_size

    # ── Main query ────────────────────────────────────────────────────────────
    rows: list[tuple[JobPosting, float | None]]
    if zero_vec:
        # Embedding model unavailable → sort by recency, score via skill overlap only
        q = (
            select(JobPosting)
            .where(*base_conditions)
            .order_by(JobPosting.created_at.desc())
            .offset(offset)
            .limit(filters.page_size)
        )
        rows = [(job, None) for job in (await db.execute(q)).scalars().all()]
    else:
        # Use pgvector cosine distance → hits HNSW index, very fast
        dist_expr = JobPosting.embedding.cosine_distance(profile_embedding)
        q = (
            select(JobPosting, dist_expr.label("cosine_dist"))
            .where(*base_conditions)
            .order_by(dist_expr)
            .offset(offset)
            .limit(filters.page_size)
        )
        rows = [(row[0], row[1]) for row in (await db.execute(q)).all()]

    # ── Score + re-rank ───────────────────────────────────────────────────────
    results: list[JobMatchResult] = []
    for row in rows:
        if zero_vec:
            job, cosine_dist = row[0], None
        else:
            job, cosine_dist = row

        vec_sim = (1.0 - cosine_dist) if cosine_dist is not None else 0.5
        skill_ov = _skill_overlap(list(job.required_skills or []), profile_skills)
        score, explanation = compute_match_score(
            vec_sim, skill_ov, profile_skills, list(job.required_skills or [])
        )
        if zero_vec:
            score = round(skill_ov * 100, 1)
            vec_sim = 0.0
            explanation.update(
                matching_mode="skills_only",
                vector_similarity_raw=0.0,
                vector_contribution=0.0,
                skill_contribution=score,
            )
        results.append(
            JobMatchResult(
                job=JobPostingRead.model_validate(job),
                score=score,
                vector_similarity=vec_sim,
                skill_overlap=skill_ov,
                explanation=explanation,
            )
        )

    # Re-rank: pgvector sorted by vector distance alone; skill overlap can shift positions
    results.sort(key=lambda r: r.score, reverse=True)
    return results, total


# ── Recruiter job CRUD ────────────────────────────────────────────────────────


async def create_recruiter_job(
    db: AsyncSession, data: JobPostingCreate, owner_id: uuid.UUID
) -> JobPosting:
    job_data = data.model_dump(exclude_none=True)
    job_data["required_skills"] = _normalize_required_skills(data.required_skills)
    job_data["category"] = classify_category(data.title, data.description)
    job_data["owner_id"] = owner_id
    job_data["source"] = "recruiter"
    job_data["external_id"] = None
    from app.users.models import User

    job_data["tenant_id"] = await db.scalar(select(User.tenant_id).where(User.id == owner_id))
    job = JobPosting(**job_data)
    db.add(job)
    await db.flush()
    return job


async def list_my_jobs(
    db: AsyncSession, owner_id: uuid.UUID, page: int = 1, page_size: int = 20
) -> tuple[list[JobPosting], int]:
    from app.users.models import User

    tenant_id = await db.scalar(select(User.tenant_id).where(User.id == owner_id))
    condition = and_(JobPosting.owner_id == owner_id, JobPosting.tenant_id == tenant_id)
    total = (
        await db.execute(select(func.count()).select_from(JobPosting).where(condition))
    ).scalar_one()
    offset = (page - 1) * page_size
    jobs = (
        (
            await db.execute(
                select(JobPosting)
                .where(condition)
                .order_by(JobPosting.created_at.desc())
                .offset(offset)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return list(jobs), total


async def update_recruiter_job(
    db: AsyncSession, job: JobPosting, data: JobPostingUpdate, *, actor_id: uuid.UUID | None = None
) -> JobPosting:
    check_version(job, data.expected_version)
    if job.publication_status == "archived":
        raise HTTPException(409, "Archivierte Inserate können nicht bearbeitet werden.")
    for key, val in data.model_dump(exclude_unset=True, exclude={"expected_version"}).items():
        if key in {"title", "company", "is_remote", "required_skills"} and val is None:
            raise HTTPException(422, "Pflichtfelder dürfen nicht geleert werden.")
        if key == "required_skills":
            val = _normalize_required_skills(val)
        setattr(job, key, val)
    await db.execute(delete(JobMatchScore).where(JobMatchScore.job_id == job.id))
    job.embedding = None
    job.publication_status = "draft"
    record_change(
        db, job, actor_id or job.owner_id, "edit", "Änderungen müssen erneut veröffentlicht werden."
    )
    # Re-classify if title or description changed
    if data.title is not None or data.description is not None:
        job.category = classify_category(job.title, job.description)
    await db.flush()
    return job


async def delete_recruiter_job(db: AsyncSession, job: JobPosting) -> None:
    from app.applications.models import Application
    from app.jobs.models import JobPublicationEvent

    if (
        job.publication_status != "draft"
        or job.published_at is not None
        or await db.scalar(select(Application.id).where(Application.job_id == job.id).limit(1))
        or await db.scalar(
            select(JobPublicationEvent.id).where(JobPublicationEvent.job_id == job.id).limit(1)
        )
    ):
        raise HTTPException(409, "Inserate mit Verlauf oder Bewerbungen bitte archivieren.")
    await db.delete(job)
    await db.flush()


# ── Candidate pipeline ────────────────────────────────────────────────────────

_GATE_THRESHOLD = 0.50  # 50 % skill overlap required to pass hard gate


async def get_candidates_for_job(
    db: AsyncSession, job: JobPosting, page: int = 1, page_size: int = 20
) -> tuple[list[CandidateMatchRead], int]:
    """
    Return candidates ranked by skill overlap against job.required_skills.
    Uses the selectin-loaded skills relationship – no extra N+1 queries.
    """
    from app.profiles.models import CandidateProfile
    from app.users.models import User

    if job.owner_id is None:
        return [], 0
    all_profiles = list(
        (
            await db.execute(
                select(CandidateProfile)
                .join(User, User.id == CandidateProfile.user_id)
                .where(candidate_visibility(job.owner_id, job.tenant_id))
            )
        ).scalars()
    )

    if not all_profiles:
        return [], 0

    # Batch-load user names
    user_ids = [p.user_id for p in all_profiles]
    users = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
    user_name: dict[uuid.UUID, str | None] = {u.id: u.full_name for u in users}

    job_skills = {s.lower() for s in (job.required_skills or [])}

    scored: list[CandidateMatchRead] = []
    for profile in all_profiles:
        profile_skill_names = {s.name.lower() for s in profile.skills}

        if not job_skills:
            overlap_pct = 1.0
            matched: list[str] = []
            missing: list[str] = []
        else:
            matched_set = job_skills & profile_skill_names
            overlap_pct = len(matched_set) / len(job_skills)
            matched = sorted(matched_set)[:10]
            missing = sorted(job_skills - profile_skill_names)[:10]

        scored.append(
            CandidateMatchRead(
                profile_id=profile.id,
                full_name=user_name.get(profile.user_id),
                headline=profile.headline,
                location=profile.location,
                score=round(overlap_pct * 100.0, 1),
                skill_overlap_pct=round(overlap_pct * 100.0, 1),
                matched_skills=matched,
                missing_skills=missing,
                passed_gate=overlap_pct >= _GATE_THRESHOLD,
            )
        )

    scored.sort(key=lambda r: r.score, reverse=True)
    total = len(scored)
    offset = (page - 1) * page_size
    return scored[offset : offset + page_size], total


# ── Direct application flow ───────────────────────────────────────────────────


async def apply_to_job(db: AsyncSession, user_id: uuid.UUID, job: JobPosting) -> Application:
    """
    Candidate applies to a recruiter job.
    Creates an Application record (status=applied) and pushes a WS notification
    to the job owner (recruiter).
    """
    from datetime import datetime

    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import selectinload

    from app.applications.models import Application, ApplicationHistory, ApplicationStatus

    job = await require_public_job(db, job.id, lock=True)

    # Prevent duplicate applications
    existing = await db.execute(
        select(Application).where(
            Application.user_id == user_id,
            Application.job_id == job.id,
        )
    )
    if existing.scalar_one_or_none():
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail="Du hast dich bereits auf diesen Job beworben.")

    now = datetime.now(UTC)
    app = Application(
        user_id=user_id,
        job_id=job.id,
        company=job.company,
        position=job.title,
        job_url=job.url,
        status=ApplicationStatus.APPLIED,
        applied_at=now,
    )
    db.add(app)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if "uq_applications_user_job" in str(exc.orig):
            from fastapi import HTTPException

            raise HTTPException(
                status_code=409,
                detail="Du hast dich bereits auf diesen Job beworben.",
            ) from exc
        raise

    db.add(
        ApplicationHistory(
            application_id=app.id,
            from_status=None,
            to_status=ApplicationStatus.APPLIED,
            note="Direkt-Bewerbung über FlintPlate",
        )
    )
    await db.flush()

    # Reload with history
    result = await db.execute(
        select(Application)
        .where(Application.id == app.id)
        .options(selectinload(Application.history))
    )
    app = result.scalar_one()

    # Notify candidate via WS
    from app.ws.manager import manager

    await manager.send_to_user(
        str(user_id),
        {
            "type": "application.created",
            "payload": {
                "id": str(app.id),
                "status": "applied",
                "company": app.company,
                "position": app.position,
            },
        },
    )

    # Notify recruiter via WS + DB notification (if job has an owner)
    if job.owner_id:
        from app.notifications.service import create_and_push
        from app.users.models import User as _User

        user_result = await db.execute(select(_User).where(_User.id == user_id))
        candidate = user_result.scalar_one_or_none()
        name = (candidate.full_name or "Jemand") if candidate else "Jemand"

        await create_and_push(
            db=db,
            user_id=job.owner_id,
            type_="application.new",
            title="Neue Bewerbung",
            body=f"{name} hat sich auf '{job.title}' beworben.",
            meta={"job_id": str(job.id), "application_id": str(app.id)},
        )

        # Email to recruiter
        recruiter_result = await db.execute(select(_User).where(_User.id == job.owner_id))
        recruiter = recruiter_result.scalar_one_or_none()
        if recruiter:
            from app.config import get_settings
            from app.email.sender import send_email

            _cfg = get_settings()
            _frontend_url = getattr(_cfg, "frontend_url", "http://localhost:3001")
            await send_email(
                to=recruiter.email,
                subject=f"Neue Bewerbung: {name} auf '{job.title}'",
                html=f"""
                <div style="font-family:sans-serif;max-width:560px;margin:auto;padding:24px">
                  <h2 style="color:#1a1a2e">Neue Bewerbung eingegangen</h2>
                  <p><strong>{name}</strong> hat sich auf Ihre Stelle <strong>{job.title}</strong> beworben.</p>
                  <a href="{_frontend_url}/dashboard/jobs/{job.id}"
                     style="display:inline-block;margin-top:16px;padding:10px 20px;
                            background:#059669;color:#fff;border-radius:8px;text-decoration:none">
                    Bewerbung ansehen
                  </a>
                  <p style="margin-top:32px;color:#888;font-size:12px">FlintPlate · neurofunken</p>
                </div>
                """,
            )

    return app


async def get_applications_for_job(
    db: AsyncSession, job_id: uuid.UUID, page: int = 1, page_size: int = 20
) -> tuple[list[RecruiterApplicationRead], int]:
    """Return all applications for a recruiter's job with candidate profile info."""
    from app.applications.models import Application
    from app.jobs.schemas import RecruiterApplicationRead
    from app.profiles.models import CandidateProfile
    from app.users.models import User

    condition = Application.job_id == job_id
    total = (
        await db.execute(select(func.count()).select_from(Application).where(condition))
    ).scalar_one()

    offset = (page - 1) * page_size
    apps = (
        (
            await db.execute(
                select(Application)
                .where(condition)
                .order_by(Application.created_at.desc())
                .offset(offset)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )

    if not apps:
        return [], total

    # Batch-load user names + profile info
    user_ids = [a.user_id for a in apps]
    users = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
    user_name: dict[uuid.UUID, str | None] = {u.id: u.full_name for u in users}

    profiles = (
        (await db.execute(select(CandidateProfile).where(CandidateProfile.user_id.in_(user_ids))))
        .scalars()
        .all()
    )
    profile_map: dict[uuid.UUID, CandidateProfile] = {p.user_id: p for p in profiles}

    # Batch-load pipeline stage assignments
    from app.pipeline.models import ApplicationStageAssignment, PipelineStage

    app_ids = [a.id for a in apps]
    stage_rows = (
        await db.execute(
            select(ApplicationStageAssignment, PipelineStage)
            .join(PipelineStage, PipelineStage.id == ApplicationStageAssignment.stage_id)
            .where(ApplicationStageAssignment.application_id.in_(app_ids))
        )
    ).all()
    stage_map: dict[uuid.UUID, PipelineStage] = {
        row.ApplicationStageAssignment.application_id: row.PipelineStage for row in stage_rows
    }

    results: list[RecruiterApplicationRead] = []
    for app in apps:
        profile = profile_map.get(app.user_id)
        stage = stage_map.get(app.id)
        results.append(
            RecruiterApplicationRead(
                id=app.id,
                user_id=app.user_id,
                candidate_name=user_name.get(app.user_id),
                candidate_headline=profile.headline if profile else None,
                candidate_location=profile.location if profile else None,
                status=app.status.value,
                applied_at=app.applied_at,
                notes=app.notes,
                created_at=app.created_at,
                pipeline_stage_id=stage.id if stage else None,
                pipeline_stage_name=stage.name if stage else None,
                pipeline_stage_color=stage.color if stage else None,
            )
        )
    return results, total


async def update_application_as_recruiter(
    db: AsyncSession, app: Application, new_status: str, note: str | None
) -> Application:
    """Recruiter updates a candidate's application status."""
    from sqlalchemy.orm import selectinload

    from app.applications.models import Application, ApplicationHistory, ApplicationStatus

    old_status = app.status
    app.status = ApplicationStatus(new_status)

    db.add(
        ApplicationHistory(
            application_id=app.id,
            from_status=old_status,
            to_status=app.status,
            note=note or f"Status durch Recruiter auf '{new_status}' gesetzt",
        )
    )
    await db.flush()

    # Reload with history
    result = await db.execute(
        select(Application)
        .where(Application.id == app.id)
        .options(selectinload(Application.history))
    )
    app = result.scalar_one()

    # Notify candidate via WebSocket + persistent DB notification
    from app.ws.manager import manager

    await manager.send_to_user(
        str(app.user_id),
        {
            "type": "application.updated",
            "payload": {
                "id": str(app.id),
                "status": app.status.value,
                "company": app.company,
                "position": app.position,
            },
        },
    )

    _STATUS_LABELS: dict[str, str] = {
        "screening": "Screening",
        "interview": "Interview",
        "offer": "Angebot",
        "rejected": "Abgelehnt",
        "withdrawn": "Zurückgezogen",
    }
    label = _STATUS_LABELS.get(app.status.value)
    if label:
        from app.notifications.service import create_and_push

        _TITLES = {
            "interview": "Interview-Einladung",
            "offer": "Angebot erhalten!",
            "rejected": "Bewerbung abgelehnt",
        }
        title = _TITLES.get(app.status.value, f"Bewerbungsstatus: {label}")
        body = f"{app.company} \u2013 {app.position}: Status wurde auf \u201e{label}\u201c gesetzt."
        await create_and_push(
            db=db,
            user_id=app.user_id,
            type_="application_status",
            title=title,
            body=body,
            meta={"application_id": str(app.id), "status": app.status.value},
        )

        # Email to candidate for key status changes
        if app.status.value in ("interview", "offer", "rejected"):
            from app.config import get_settings
            from app.email.sender import send_email
            from app.users.models import User as _CandUser

            candidate_result = await db.execute(
                select(_CandUser).where(_CandUser.id == app.user_id)
            )
            cand_user = candidate_result.scalar_one_or_none()
            if cand_user:
                _cfg = get_settings()
                _frontend_url = getattr(_cfg, "frontend_url", "http://localhost:3001")
                _email_body_map = {
                    "interview": f"Herzlichen Glückwunsch! Du wurdest zu einem Interview für <strong>{app.position}</strong> bei <strong>{app.company}</strong> eingeladen.",
                    "offer": f"Fantastische Neuigkeiten! Du hast ein Angebot für <strong>{app.position}</strong> bei <strong>{app.company}</strong> erhalten.",
                    "rejected": f"Leider wurde deine Bewerbung als <strong>{app.position}</strong> bei <strong>{app.company}</strong> nicht weiterverfolgt.",
                }
                await send_email(
                    to=cand_user.email,
                    subject=title,
                    html=f"""
                    <div style="font-family:sans-serif;max-width:560px;margin:auto;padding:24px">
                      <h2 style="color:#1a1a2e">{title}</h2>
                      <p>{_email_body_map[app.status.value]}</p>
                      <a href="{_frontend_url}/applications"
                         style="display:inline-block;margin-top:16px;padding:10px 20px;
                                background:#7F77DD;color:#fff;border-radius:8px;text-decoration:none">
                        Bewerbungen öffnen
                      </a>
                      <p style="margin-top:32px;color:#888;font-size:12px">FlintPlate · neurofunken</p>
                    </div>
                    """,
                )

    return app


# ── Market Stats + Skills Gap ─────────────────────────────────────────────────

# v2: Skill metadata – category, difficulty, estimated learning hours
_SKILL_META: dict[str, dict[str, Any]] = {
    # Frontend
    "react": {"category": "Frontend", "difficulty": "intermediate", "hours": 40},
    "typescript": {"category": "Frontend", "difficulty": "intermediate", "hours": 30},
    "javascript": {"category": "Frontend", "difficulty": "beginner", "hours": 50},
    "nextjs": {"category": "Frontend", "difficulty": "intermediate", "hours": 25},
    "vue": {"category": "Frontend", "difficulty": "intermediate", "hours": 30},
    "angular": {"category": "Frontend", "difficulty": "advanced", "hours": 60},
    "css": {"category": "Frontend", "difficulty": "beginner", "hours": 20},
    # Backend
    "python": {"category": "Backend", "difficulty": "beginner", "hours": 40},
    "fastapi": {"category": "Backend", "difficulty": "intermediate", "hours": 20},
    "java": {"category": "Backend", "difficulty": "intermediate", "hours": 60},
    "golang": {"category": "Backend", "difficulty": "intermediate", "hours": 50},
    "rust": {"category": "Backend", "difficulty": "advanced", "hours": 80},
    "graphql": {"category": "Backend", "difficulty": "intermediate", "hours": 20},
    "node.js": {"category": "Backend", "difficulty": "intermediate", "hours": 35},
    # DevOps / Cloud
    "docker": {"category": "DevOps", "difficulty": "intermediate", "hours": 20},
    "kubernetes": {"category": "DevOps", "difficulty": "advanced", "hours": 40},
    "aws": {"category": "DevOps", "difficulty": "intermediate", "hours": 50},
    "terraform": {"category": "DevOps", "difficulty": "intermediate", "hours": 30},
    "ci/cd": {"category": "DevOps", "difficulty": "intermediate", "hours": 20},
    "devops": {"category": "DevOps", "difficulty": "intermediate", "hours": 40},
    "linux": {"category": "DevOps", "difficulty": "beginner", "hours": 25},
    "git": {"category": "DevOps", "difficulty": "beginner", "hours": 10},
    # Data / AI
    "sql": {"category": "Data", "difficulty": "beginner", "hours": 30},
    "postgresql": {"category": "Data", "difficulty": "intermediate", "hours": 20},
    "machine learning": {"category": "Data", "difficulty": "advanced", "hours": 80},
    "deep learning": {"category": "Data", "difficulty": "advanced", "hours": 100},
    "data analysis": {"category": "Data", "difficulty": "intermediate", "hours": 40},
    "tensorflow": {"category": "Data", "difficulty": "advanced", "hours": 60},
    "pytorch": {"category": "Data", "difficulty": "advanced", "hours": 60},
    "nlp": {"category": "Data", "difficulty": "advanced", "hours": 70},
    "spark": {"category": "Data", "difficulty": "advanced", "hours": 50},
    "power bi": {"category": "Data", "difficulty": "beginner", "hours": 20},
    "tableau": {"category": "Data", "difficulty": "beginner", "hours": 20},
    # DB / Infra
    "redis": {"category": "Infra", "difficulty": "intermediate", "hours": 15},
    "mongodb": {"category": "Infra", "difficulty": "intermediate", "hours": 20},
    # Agile / Mgmt
    "agile": {"category": "Management", "difficulty": "beginner", "hours": 15},
    "scrum": {"category": "Management", "difficulty": "beginner", "hours": 10},
    "excel": {"category": "Management", "difficulty": "beginner", "hours": 15},
    # Marketing
    "seo": {"category": "Marketing", "difficulty": "beginner", "hours": 20},
    "marketing": {"category": "Marketing", "difficulty": "beginner", "hours": 25},
}

# Curated course recommendations: skill (lowercase) → URL
_COURSE_MAP: dict[str, str] = {
    "python": "https://www.udemy.com/course/complete-python-bootcamp/",
    "javascript": "https://www.udemy.com/course/the-complete-javascript-course/",
    "typescript": "https://www.udemy.com/course/understanding-typescript/",
    "react": "https://www.udemy.com/course/react-the-complete-guide-incl-redux/",
    "docker": "https://www.udemy.com/course/docker-mastery/",
    "kubernetes": "https://www.udemy.com/course/certified-kubernetes-administrator-with-practice-tests/",
    "aws": "https://www.udemy.com/course/aws-certified-solutions-architect-associate-saa-c03/",
    "sql": "https://www.udemy.com/course/the-complete-sql-bootcamp/",
    "postgresql": "https://www.udemy.com/course/sql-and-postgresql/",
    "fastapi": "https://www.udemy.com/course/fastapi-the-complete-course/",
    "machine learning": "https://www.coursera.org/specializations/machine-learning-introduction",
    "deep learning": "https://www.coursera.org/specializations/deep-learning",
    "data analysis": "https://www.coursera.org/professional-certificates/google-data-analytics",
    "java": "https://www.udemy.com/course/java-the-complete-java-developer-course/",
    "golang": "https://www.udemy.com/course/learn-how-to-code/",
    "rust": "https://www.udemy.com/course/ultimate-rust-crash-course/",
    "linux": "https://www.udemy.com/course/complete-linux-training-course-to-get-your-dream-it-job/",
    "git": "https://www.udemy.com/course/git-complete/",
    "agile": "https://www.coursera.org/professional-certificates/google-project-management",
    "scrum": "https://www.scrum.org/resources/what-is-scrum",
    "excel": "https://www.coursera.org/learn/excel-basics-data-analysis-ibm",
    "power bi": "https://www.udemy.com/course/microsoft-power-bi-up-running-with-power-bi-desktop/",
    "tableau": "https://www.udemy.com/course/tableau10/",
    "tensorflow": "https://www.coursera.org/professional-certificates/tensorflow-in-practice",
    "pytorch": "https://www.udemy.com/course/pytorch-for-deep-learning/",
    "nlp": "https://www.coursera.org/specializations/natural-language-processing",
    "spark": "https://www.udemy.com/course/spark-and-python-for-big-data-with-pyspark/",
    "redis": "https://www.udemy.com/course/redis-beginner-to-advanced/",
    "mongodb": "https://www.mongodb.com/university",
    "graphql": "https://www.udemy.com/course/graphql-with-react-course/",
    "nextjs": "https://www.udemy.com/course/nextjs-react-the-complete-guide/",
    "vue": "https://www.udemy.com/course/vuejs-2-the-complete-guide/",
    "angular": "https://www.udemy.com/course/the-complete-guide-to-angular-2/",
    "devops": "https://www.udemy.com/course/learn-devops-the-complete-kubernetes-course/",
    "terraform": "https://www.udemy.com/course/learn-devops-infrastructure-automation-with-terraform/",
    "ci/cd": "https://www.udemy.com/course/gitlab-ci-pipelines-ci-cd-and-devops-for-beginners/",
    "seo": "https://www.coursera.org/specializations/seo",
    "marketing": "https://www.coursera.org/professional-certificates/google-digital-marketing-ecommerce",
}


async def get_market_stats(db: AsyncSession) -> MarketStats:
    """
    Aggregate job market statistics from the current job_postings table.
    Pure SQL / Python aggregation – no ML, fast enough for request-time.
    """
    from collections import Counter, defaultdict

    # Load lightweight projection: only fields needed for stats
    rows = (
        await db.execute(
            select(
                JobPosting.category,
                JobPosting.is_remote,
                JobPosting.salary_min,
                JobPosting.salary_max,
                JobPosting.required_skills,
                JobPosting.employment_type,
            ).where(public_job_condition())
        )
    ).all()

    if not rows:
        return MarketStats(
            total_jobs=0,
            remote_count=0,
            remote_pct=0.0,
            top_skills=[],
            categories=[],
            salary_by_category=[],
            employment_types=[],
        )

    total = len(rows)
    remote_count = sum(1 for r in rows if r.is_remote)

    # Skills frequency
    skill_counter: Counter[str] = Counter()
    for r in rows:
        for skill in r.required_skills or []:
            skill_counter[skill.lower()] += 1

    top_skills = [
        {"skill": skill, "count": cnt, "pct": round(cnt / total * 100, 1)}
        for skill, cnt in skill_counter.most_common(30)
    ]

    # Category frequency
    cat_counter: Counter[str] = Counter(r.category or "Sonstige" for r in rows)
    categories = [
        {"category": cat, "count": cnt, "pct": round(cnt / total * 100, 1)}
        for cat, cnt in cat_counter.most_common()
    ]

    # Salary by category
    salary_data: dict[str, list[tuple[int | None, int | None]]] = defaultdict(list)
    for r in rows:
        if r.salary_min or r.salary_max:
            salary_data[r.category or "Sonstige"].append((r.salary_min, r.salary_max))

    salary_by_cat: list[SalaryStat] = []
    for cat, pairs in sorted(salary_data.items(), key=lambda x: -len(x[1])):
        mins = [p[0] for p in pairs if p[0]]
        maxs = [p[1] for p in pairs if p[1]]
        mids = [(p[0] + p[1]) / 2 for p in pairs if p[0] and p[1]]
        salary_by_cat.append(
            SalaryStat(
                category=cat,
                count=len(pairs),
                salary_min_avg=round(sum(mins) / len(mins)) if mins else None,
                salary_max_avg=round(sum(maxs) / len(maxs)) if maxs else None,
                salary_mid=round(sum(mids) / len(mids)) if mids else None,
            )
        )

    # Employment types
    type_counter: Counter[str] = Counter(r.employment_type or "nicht angegeben" for r in rows)
    employment_types = [{"type": t, "count": cnt} for t, cnt in type_counter.most_common()]

    return MarketStats(
        total_jobs=total,
        remote_count=remote_count,
        remote_pct=round(remote_count / total * 100, 1),
        top_skills=top_skills,
        categories=categories,
        salary_by_category=salary_by_cat,
        employment_types=employment_types,
    )


async def get_profile_gap_analysis(db: AsyncSession, profile_id: uuid.UUID) -> ProfileGapAnalysis:
    """
    Compare the candidate's skills against overall market demand.
    v2: Returns learning paths grouped by category with difficulty + time estimates.
    """
    from collections import Counter, defaultdict

    from app.profiles.models import CandidateProfile

    # Load profile skills
    profile = (
        await db.execute(select(CandidateProfile).where(CandidateProfile.id == profile_id))
    ).scalar_one_or_none()

    my_skill_names: set[str] = set()
    if profile:
        my_skill_names = {s.name.lower() for s in profile.skills}

    # Market skill frequencies (top 50 only)
    rows = (
        (await db.execute(select(JobPosting.required_skills).where(public_job_condition())))
        .scalars()
        .all()
    )
    total_jobs = len(rows)
    if total_jobs == 0:
        return ProfileGapAnalysis(
            my_skills=sorted(my_skill_names),
            top_gaps=[],
            coverage_pct=0.0,
            strong_skills=[],
            learning_paths=[],
        )

    counter: Counter[str] = Counter()
    for skills_list in rows:
        for s in skills_list or []:
            counter[s.lower()] += 1

    top_50 = counter.most_common(50)

    # Coverage
    top_50_skills = {s for s, _ in top_50}
    covered = top_50_skills & my_skill_names
    coverage_pct = round(len(covered) / len(top_50_skills) * 100, 1) if top_50_skills else 0.0

    # Gaps with v2 enrichment
    gaps: list[SkillGap] = []
    for skill, cnt in top_50:
        if skill not in my_skill_names:
            meta = _SKILL_META.get(skill, {})
            difficulty = meta.get("difficulty", "intermediate")
            est_hours = meta.get("hours", 40)
            diff_factor = {"beginner": 1.5, "intermediate": 1.0, "advanced": 0.6}.get(
                difficulty, 1.0
            )
            demand_pct = round(cnt / total_jobs * 100, 1)
            gaps.append(
                SkillGap(
                    skill=skill,
                    market_demand_pct=demand_pct,
                    course_url=_COURSE_MAP.get(skill),
                    category=meta.get("category"),
                    difficulty=difficulty,
                    est_hours=est_hours,
                    priority_score=round(demand_pct * diff_factor, 2),
                )
            )

    gaps.sort(key=lambda g: g.priority_score, reverse=True)

    # Learning paths: group gaps by category
    by_cat: dict[str, list[SkillGap]] = defaultdict(list)
    for g in gaps:
        cat = g.category or "Sonstige"
        by_cat[cat].append(g)

    learning_paths = [
        LearningPath(
            category=cat,
            skills=sorted(skill_list, key=lambda g: g.priority_score, reverse=True),
            total_hours=sum(g.est_hours or 0 for g in skill_list),
        )
        for cat, skill_list in sorted(
            by_cat.items(), key=lambda x: -sum(g.priority_score for g in x[1])
        )
    ]

    strong = [s for s, _ in top_50 if s in my_skill_names]

    return ProfileGapAnalysis(
        my_skills=sorted(my_skill_names),
        top_gaps=gaps[:20],
        coverage_pct=coverage_pct,
        strong_skills=strong[:10],
        learning_paths=learning_paths[:6],
    )
