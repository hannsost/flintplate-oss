"""Zeitarbeit service – dispositions engine + AÜG compliance."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.profiles.models import CandidateProfile
from app.users.models import User
from app.zeitarbeit.models import Disposition, TempWorkerAvailability, WorkAssignment
from app.zeitarbeit.schemas import (
    AssignmentCreate,
    AssignmentRead,
    AssignmentUpdate,
    AvailabilityRead,
    AvailabilityUpsert,
    CanvasAssignPayload,
    DispositionRead,
    DispositionUpdate,
    JobCanvasRead,
    PoolWorkerRead,
    WorkerCanvasRead,
    ZeitarbeitStats,
)

# AÜG: 18 months max placement, yellow warning at 15 months
_AUG_MAX = Decimal("18")
_AUG_WARN = Decimal("15")


def _aueg_status(placed: Decimal) -> str:
    remaining = _AUG_MAX - placed
    if remaining <= 0:
        return "red"
    if placed >= _AUG_WARN:
        return "yellow"
    return "green"


def _availability_read(av: TempWorkerAvailability) -> AvailabilityRead:
    placed = av.total_placed_months
    remaining = max(Decimal("0"), _AUG_MAX - placed)
    return AvailabilityRead(
        id=av.id,
        user_id=av.user_id,
        is_in_pool=av.is_in_pool,
        available_from=av.available_from,
        available_until=av.available_until,
        preferred_shift=av.preferred_shift,
        preferred_location=av.preferred_location,
        max_commute_km=av.max_commute_km,
        total_placed_months=placed,
        notes=av.notes,
        updated_at=av.updated_at,
        aueg_remaining_months=remaining,
        aueg_status=_aueg_status(placed),
    )


# ── Assignments ───────────────────────────────────────────────────────────────


async def create_assignment(
    db: AsyncSession,
    recruiter_id: uuid.UUID,
    data: AssignmentCreate,
) -> AssignmentRead:
    recruiter = await db.get(User, recruiter_id)
    if recruiter is None or recruiter.tenant_id is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Keine Organisation zugewiesen.")
    assignment = WorkAssignment(
        recruiter_id=recruiter_id,
        tenant_id=recruiter.tenant_id,
        **data.model_dump(),
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return AssignmentRead.model_validate(assignment)


async def list_assignments(
    db: AsyncSession,
    recruiter_id: uuid.UUID,
    status: str | None = None,
) -> list[AssignmentRead]:
    q = select(WorkAssignment).where(WorkAssignment.recruiter_id == recruiter_id)
    if status:
        q = q.where(WorkAssignment.status == status)
    q = q.order_by(WorkAssignment.created_at.desc())
    result = await db.execute(q)
    return [AssignmentRead.model_validate(r) for r in result.scalars().all()]


async def get_assignment(db: AsyncSession, assignment_id: uuid.UUID) -> WorkAssignment | None:
    return await db.get(WorkAssignment, assignment_id)


async def update_assignment(
    db: AsyncSession,
    assignment: WorkAssignment,
    data: AssignmentUpdate,
) -> AssignmentRead:
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(assignment, field, value)
    assignment.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(assignment)
    return AssignmentRead.model_validate(assignment)


async def delete_assignment(db: AsyncSession, assignment: WorkAssignment) -> None:
    await db.delete(assignment)
    await db.commit()


# ── Dispositions engine ───────────────────────────────────────────────────────


async def run_matching(
    db: AsyncSession,
    assignment: WorkAssignment,
    limit: int = 20,
) -> list[DispositionRead]:
    """Score all pool workers against this assignment.

    Scoring = 60% skill-overlap + 30% embedding similarity + 10% shift bonus.
    Falls back to skill-only if embeddings unavailable.
    """
    from app.jobs.embeddings import cosine_similarity, embed_texts

    required = {s.lower() for s in (assignment.required_skills or [])}

    # Embed the assignment title + required skills for semantic matching
    assign_text = f"{assignment.title}. Skills: {', '.join(assignment.required_skills or [])}"
    assign_vectors = await embed_texts([assign_text])
    assign_vec = assign_vectors[0]
    has_embeddings = any(v != 0.0 for v in assign_vec)

    # Load all in-pool workers with profiles
    if assignment.tenant_id is None:
        return []
    av_result = await db.execute(
        select(TempWorkerAvailability)
        .join(User, User.id == TempWorkerAvailability.user_id)
        .where(
            TempWorkerAvailability.is_in_pool.is_(True),
            User.tenant_id == assignment.tenant_id,
            User.is_active.is_(True),
        )
    )
    availabilities = av_result.scalars().all()
    if not availabilities:
        return []

    worker_ids = [av.user_id for av in availabilities]
    av_map = {av.user_id: av for av in availabilities}

    # Load profiles + skills
    profile_result = await db.execute(
        select(CandidateProfile).where(CandidateProfile.user_id.in_(worker_ids))
    )
    profiles = profile_result.scalars().all()
    profile_map = {p.user_id: p for p in profiles}

    # Load users for names
    user_result = await db.execute(select(User).where(User.id.in_(worker_ids)))
    user_map = {u.id: u for u in user_result.scalars().all()}

    # Embed all candidate profiles in one batch
    profile_texts: list[str] = []
    profile_wids: list[uuid.UUID] = []
    for wid in worker_ids:
        p = profile_map.get(wid)
        if p:
            skills_str = ", ".join(s.name for s in (p.skills or []))
            profile_texts.append(f"{p.headline or ''}. Skills: {skills_str}")
            profile_wids.append(wid)

    profile_vecs: dict[uuid.UUID, list[float]] = {}
    if has_embeddings and profile_texts:
        vecs = await embed_texts(profile_texts)
        profile_vecs = dict(zip(profile_wids, vecs, strict=True))

    scored: list[tuple[float, uuid.UUID, list[str], list[str]]] = []
    for wid in worker_ids:
        profile = profile_map.get(wid)
        av = av_map[wid]

        # AÜG gate: skip workers at limit
        if av.total_placed_months >= _AUG_MAX:
            continue

        worker_skills: set[str] = set()
        if profile and profile.skills:
            worker_skills = {s.name.lower() for s in profile.skills}

        # Skill overlap component (60%)
        if required:
            matched = required & worker_skills
            missing = required - worker_skills
            skill_score = len(matched) / len(required)
        else:
            matched, missing = set(), set()
            skill_score = 1.0

        # Embedding similarity component (30%)
        emb_score = 0.0
        if has_embeddings and wid in profile_vecs:
            emb_score = max(0.0, cosine_similarity(assign_vec, profile_vecs[wid]))

        # Shift bonus (10%)
        shift_bonus = 0.0
        if assignment.shift and av.preferred_shift and av.preferred_shift == assignment.shift:
            shift_bonus = 1.0

        if has_embeddings:
            score = 0.60 * skill_score + 0.30 * emb_score + 0.10 * shift_bonus
        else:
            score = skill_score + 0.1 * shift_bonus

        scored.append((min(1.0, score), wid, sorted(matched), sorted(missing)))

    scored.sort(key=lambda x: x[0], reverse=True)
    scored = scored[:limit]

    # Upsert dispositions
    results: list[DispositionRead] = []
    for score, wid, matched_list, missing_list in scored:
        # Check if disposition already exists
        existing_result = await db.execute(
            select(Disposition).where(
                Disposition.assignment_id == assignment.id,
                Disposition.worker_id == wid,
            )
        )
        disp = existing_result.scalar_one_or_none()
        if disp is None:
            disp = Disposition(
                assignment_id=assignment.id,
                worker_id=wid,
                score=Decimal(str(round(score, 4))),
                matched_skills=matched_list,
                missing_skills=missing_list,
                status="suggested",
            )
            db.add(disp)
        else:
            disp.score = Decimal(str(round(score, 4)))
            disp.matched_skills = matched_list
            disp.missing_skills = missing_list

        await db.flush()
        user = user_map.get(wid)
        profile = profile_map.get(wid)
        results.append(
            DispositionRead(
                id=disp.id,
                assignment_id=assignment.id,
                worker_id=wid,
                worker_name=user.full_name if user else None,
                worker_headline=profile.headline if profile else None,
                score=Decimal(str(round(score, 4))),
                matched_skills=matched_list,
                missing_skills=missing_list,
                status=disp.status,
                started_at=disp.started_at,
                ended_at=disp.ended_at,
                notes=disp.notes,
                created_at=disp.created_at or datetime.now(UTC),
            )
        )

    await db.commit()
    return results


async def get_dispositions(
    db: AsyncSession,
    assignment_id: uuid.UUID,
) -> list[DispositionRead]:
    result = await db.execute(
        select(Disposition)
        .where(Disposition.assignment_id == assignment_id)
        .order_by(Disposition.score.desc())
    )
    disps = result.scalars().all()

    worker_ids = [d.worker_id for d in disps]
    user_result = await db.execute(select(User).where(User.id.in_(worker_ids)))
    user_map = {u.id: u for u in user_result.scalars().all()}

    profile_result = await db.execute(
        select(CandidateProfile).where(CandidateProfile.user_id.in_(worker_ids))
    )
    profile_map = {p.user_id: p for p in profile_result.scalars().all()}

    out = []
    for d in disps:
        user = user_map.get(d.worker_id)
        profile = profile_map.get(d.worker_id)
        out.append(
            DispositionRead(
                id=d.id,
                assignment_id=d.assignment_id,
                worker_id=d.worker_id,
                worker_name=user.full_name if user else None,
                worker_headline=profile.headline if profile else None,
                score=d.score,
                matched_skills=d.matched_skills or [],
                missing_skills=d.missing_skills or [],
                status=d.status,
                started_at=d.started_at,
                ended_at=d.ended_at,
                notes=d.notes,
                created_at=d.created_at,
            )
        )
    return out


async def update_disposition(
    db: AsyncSession,
    assignment_id: uuid.UUID,
    worker_id: uuid.UUID,
    data: DispositionUpdate,
) -> DispositionRead | None:
    result = await db.execute(
        select(Disposition)
        .where(
            Disposition.assignment_id == assignment_id,
            Disposition.worker_id == worker_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    disp = result.scalar_one_or_none()
    if not disp:
        return None

    start = data.started_at or disp.started_at
    end = data.ended_at or disp.ended_at
    if start and end and end < start:
        raise HTTPException(status_code=422, detail="Ende darf nicht vor Beginn liegen.")
    old_months = Decimal("0")
    if disp.status in {"active", "completed"} and disp.started_at and disp.ended_at:
        old_months = Decimal(str(round((disp.ended_at - disp.started_at).days / 30.44, 2)))
    disp.status = data.status
    if data.started_at is not None:
        disp.started_at = data.started_at
    if data.ended_at is not None:
        disp.ended_at = data.ended_at
    if data.notes is not None:
        disp.notes = data.notes

    # Apply the difference so repeated status updates do not count the period twice.
    months = Decimal("0")
    if data.status in {"active", "completed"} and disp.started_at and disp.ended_at:
        delta = (disp.ended_at - disp.started_at).days
        months = Decimal(str(round(delta / 30.44, 2)))
    if months != old_months:
        av_result = await db.execute(
            select(TempWorkerAvailability)
            .where(TempWorkerAvailability.user_id == worker_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        av = av_result.scalar_one_or_none()
        if av:
            av.total_placed_months = max(Decimal("0"), av.total_placed_months + months - old_months)

    await db.commit()
    await db.refresh(disp)

    user = await db.get(User, disp.worker_id)
    profile_result = await db.execute(
        select(CandidateProfile).where(CandidateProfile.user_id == disp.worker_id)
    )
    profile = profile_result.scalar_one_or_none()

    return DispositionRead(
        id=disp.id,
        assignment_id=disp.assignment_id,
        worker_id=disp.worker_id,
        worker_name=user.full_name if user else None,
        worker_headline=profile.headline if profile else None,
        score=disp.score,
        matched_skills=disp.matched_skills or [],
        missing_skills=disp.missing_skills or [],
        status=disp.status,
        started_at=disp.started_at,
        ended_at=disp.ended_at,
        notes=disp.notes,
        created_at=disp.created_at,
    )


# ── Availability ──────────────────────────────────────────────────────────────


async def upsert_availability(
    db: AsyncSession,
    user_id: uuid.UUID,
    data: AvailabilityUpsert,
) -> AvailabilityRead:
    result = await db.execute(
        select(TempWorkerAvailability).where(TempWorkerAvailability.user_id == user_id)
    )
    av = result.scalar_one_or_none()
    if av is None:
        av = TempWorkerAvailability(user_id=user_id, **data.model_dump())
        db.add(av)
    else:
        for field, value in data.model_dump().items():
            setattr(av, field, value)
        av.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(av)
    return _availability_read(av)


async def get_availability(db: AsyncSession, user_id: uuid.UUID) -> AvailabilityRead | None:
    result = await db.execute(
        select(TempWorkerAvailability).where(TempWorkerAvailability.user_id == user_id)
    )
    av = result.scalar_one_or_none()
    return _availability_read(av) if av else None


def _pool_worker_read(
    av: TempWorkerAvailability, user: User | None, profile: CandidateProfile | None
) -> PoolWorkerRead:
    skills = [s.name for s in profile.skills] if profile and profile.skills else []
    return PoolWorkerRead(
        user_id=av.user_id,
        full_name=user.full_name if user else None,
        headline=profile.headline if profile else None,
        location=profile.location if profile else None,
        aueg_remaining_months=max(Decimal("0"), _AUG_MAX - av.total_placed_months),
        aueg_status=_aueg_status(av.total_placed_months),
        total_placed_months=av.total_placed_months,
        preferred_shift=av.preferred_shift,
        skills=skills,
    )


async def list_canvas_pool_workers(
    db: AsyncSession, tenant_id: uuid.UUID | None = None
) -> list[PoolWorkerRead]:
    """Pool-Worker als PoolWorkerRead (mit Name, Headline, Skills) für den Canvas."""
    if tenant_id is None:
        return []
    stmt = select(TempWorkerAvailability).where(TempWorkerAvailability.is_in_pool.is_(True))
    if tenant_id:
        stmt = stmt.join(User, User.id == TempWorkerAvailability.user_id).where(
            User.tenant_id == tenant_id, User.is_active.is_(True)
        )
    stmt = stmt.order_by(TempWorkerAvailability.updated_at.desc())
    av_result = await db.execute(stmt)
    availabilities = av_result.scalars().all()
    if not availabilities:
        return []

    worker_ids = [av.user_id for av in availabilities]

    user_result = await db.execute(select(User).where(User.id.in_(worker_ids)))
    user_map = {u.id: u for u in user_result.scalars().all()}

    profile_result = await db.execute(
        select(CandidateProfile).where(CandidateProfile.user_id.in_(worker_ids))
    )
    profile_map = {p.user_id: p for p in profile_result.scalars().all()}

    result = []
    for av in availabilities:
        user = user_map.get(av.user_id)
        profile = profile_map.get(av.user_id)
        result.append(_pool_worker_read(av, user, profile))
    return result


async def list_pool_workers(
    db: AsyncSession, tenant_id: uuid.UUID | None = None
) -> list[AvailabilityRead]:
    if tenant_id is None:
        return []
    stmt = select(TempWorkerAvailability).where(TempWorkerAvailability.is_in_pool.is_(True))
    if tenant_id:
        stmt = stmt.join(User, User.id == TempWorkerAvailability.user_id).where(
            User.tenant_id == tenant_id, User.is_active.is_(True)
        )
    stmt = stmt.order_by(TempWorkerAvailability.updated_at.desc())
    result = await db.execute(stmt)
    return [_availability_read(av) for av in result.scalars().all()]


# ── Stats ─────────────────────────────────────────────────────────────────────


async def get_zeitarbeit_stats(
    db: AsyncSession,
    recruiter_id: uuid.UUID,
) -> ZeitarbeitStats:
    total = (
        await db.execute(
            select(func.count(WorkAssignment.id)).where(WorkAssignment.recruiter_id == recruiter_id)
        )
    ).scalar_one()

    active = (
        await db.execute(
            select(func.count(WorkAssignment.id)).where(
                WorkAssignment.recruiter_id == recruiter_id,
                WorkAssignment.status == "active",
            )
        )
    ).scalar_one()

    tenant_id = await db.scalar(select(User.tenant_id).where(User.id == recruiter_id))
    pool_count = len(await list_pool_workers(db, tenant_id))

    # Dispositions for this recruiter's assignments
    total_disp = (
        await db.execute(
            select(func.count(Disposition.id))
            .join(WorkAssignment, Disposition.assignment_id == WorkAssignment.id)
            .where(WorkAssignment.recruiter_id == recruiter_id)
        )
    ).scalar_one()

    active_disp = (
        await db.execute(
            select(func.count(Disposition.id))
            .join(WorkAssignment, Disposition.assignment_id == WorkAssignment.id)
            .where(
                WorkAssignment.recruiter_id == recruiter_id,
                Disposition.status == "active",
            )
        )
    ).scalar_one()

    avg_score = (
        await db.execute(
            select(func.coalesce(func.avg(Disposition.score), 0))
            .join(WorkAssignment, Disposition.assignment_id == WorkAssignment.id)
            .where(WorkAssignment.recruiter_id == recruiter_id)
        )
    ).scalar_one()

    return ZeitarbeitStats(
        total_assignments=int(total),
        active_assignments=int(active),
        workers_in_pool=int(pool_count),
        total_dispositions=int(total_disp),
        active_dispositions=int(active_disp),
        avg_fill_score=Decimal(str(avg_score)).quantize(Decimal("0.01")),
    )


# ── Workforce Canvas ───────────────────────────────────────────────────────────


async def canvas_job_view(
    db: AsyncSession,
    assignment_id: uuid.UUID,
) -> JobCanvasRead | None:
    """Job-first view: Auftrag + gerankte Dispositions-Karten + Pool-Größe."""
    assignment = await get_assignment(db, assignment_id)
    if not assignment:
        return None

    dispositions = await get_dispositions(db, assignment_id)

    pool_size = len(await list_pool_workers(db, assignment.tenant_id))

    return JobCanvasRead(
        assignment=AssignmentRead.model_validate(assignment),
        dispositions=dispositions,
        pool_size=pool_size,
    )


async def canvas_worker_view(
    db: AsyncSession,
    worker_id: uuid.UUID,
    recruiter_id: uuid.UUID,
) -> WorkerCanvasRead | None:
    """Worker-first view: Pool-Worker + aktive Aufträge + Empfehlungen."""
    tenant_id = await db.scalar(select(User.tenant_id).where(User.id == recruiter_id))
    user = await db.get(User, worker_id)
    if tenant_id is None or user is None or user.tenant_id != tenant_id or not user.is_active:
        return None
    av_result = await db.execute(
        select(TempWorkerAvailability).where(TempWorkerAvailability.user_id == worker_id)
    )
    av = av_result.scalar_one_or_none()
    if not av or not av.is_in_pool:
        return None

    user = await db.get(User, worker_id)
    profile_result = await db.execute(
        select(CandidateProfile).where(CandidateProfile.user_id == worker_id)
    )
    profile = profile_result.scalar_one_or_none()

    worker_read = _pool_worker_read(av, user, profile)

    # Aktive Aufträge (Dispositions mit status active/confirmed)
    active_disp_result = await db.execute(
        select(Disposition).where(
            Disposition.worker_id == worker_id,
            Disposition.status.in_(["active", "confirmed"]),
        )
    )
    active_assignment_ids = [d.assignment_id for d in active_disp_result.scalars().all()]
    active_assignments: list[AssignmentRead] = []
    if active_assignment_ids:
        ass_result = await db.execute(
            select(WorkAssignment).where(
                WorkAssignment.id.in_(active_assignment_ids), WorkAssignment.tenant_id == tenant_id
            )
        )
        active_assignments = [AssignmentRead.model_validate(a) for a in ass_result.scalars().all()]

    # Empfohlene Aufträge: offene recruiter-Aufträge, bei denen der Worker noch nicht drin ist
    all_open_result = await db.execute(
        select(WorkAssignment)
        .where(
            WorkAssignment.recruiter_id == recruiter_id,
            WorkAssignment.status.in_(["incoming", "matching"]),
            WorkAssignment.id.not_in(active_assignment_ids),
        )
        .limit(10)
    )
    recommended_assignments = [
        AssignmentRead.model_validate(a) for a in all_open_result.scalars().all()
    ]

    return WorkerCanvasRead(
        worker=worker_read,
        active_assignments=active_assignments,
        recommended_assignments=recommended_assignments,
    )


async def canvas_assign(
    db: AsyncSession,
    payload: CanvasAssignPayload,
) -> DispositionRead | None:
    """Drag-drop Zuweisung: Setzt einen Worker auf einen Auftrag (confirmed)."""
    assignment = await db.scalar(
        select(WorkAssignment).where(WorkAssignment.id == payload.assignment_id).with_for_update()
    )
    worker = await db.get(User, payload.worker_id)
    availability = await db.scalar(
        select(TempWorkerAvailability).where(TempWorkerAvailability.user_id == payload.worker_id)
    )
    if (
        assignment is None
        or assignment.tenant_id is None
        or worker is None
        or worker.tenant_id != assignment.tenant_id
        or not worker.is_active
        or availability is None
        or not availability.is_in_pool
    ):
        raise HTTPException(status_code=404, detail="Worker nicht im eigenen Pool.")
    existing_result = await db.execute(
        select(Disposition).where(
            Disposition.assignment_id == payload.assignment_id,
            Disposition.worker_id == payload.worker_id,
        )
    )
    disp = existing_result.scalar_one_or_none()

    if disp is None:
        disp = Disposition(
            assignment_id=payload.assignment_id,
            worker_id=payload.worker_id,
            score=Decimal("0"),
            matched_skills=[],
            missing_skills=[],
            status=payload.status,
        )
        db.add(disp)
    else:
        disp.status = payload.status

    await db.commit()
    await db.refresh(disp)

    user = await db.get(User, payload.worker_id)
    profile_result = await db.execute(
        select(CandidateProfile).where(CandidateProfile.user_id == payload.worker_id)
    )
    profile = profile_result.scalar_one_or_none()

    return DispositionRead(
        id=disp.id,
        assignment_id=disp.assignment_id,
        worker_id=disp.worker_id,
        worker_name=user.full_name if user else None,
        worker_headline=profile.headline if profile else None,
        score=disp.score,
        matched_skills=disp.matched_skills or [],
        missing_skills=disp.missing_skills or [],
        status=disp.status,
        started_at=disp.started_at,
        ended_at=disp.ended_at,
        notes=disp.notes,
        created_at=disp.created_at,
    )
