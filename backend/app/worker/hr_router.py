"""HR/Recruiter endpoints for worker management — mounted at /zeitarbeit/workers.

All endpoints require role recruiter or admin.
Provides per-worker AND bulk configuration — straight-forward, no ceremony.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.dependencies import DBSession, TenantRecruiterUser
from app.teams.models import Team
from app.users.models import User
from app.worker.access import require_member
from app.worker.models import ALL_MODULES, WorkerSettings
from app.worker.schemas import (
    ManagerRead,
    TeamSummaryRead,
    WorkerActivateRequest,
    WorkerBulkRequest,
    WorkerListRead,
    WorkerSettingsRead,
    WorkerSettingsUpdate,
)


class HireFromApplicationRequest(BaseModel):
    """Advance an application to 'offer' and activate the candidate as worker in one step.
    Triggered when a recruiter clicks 'Als Zeitarbeiter einstellen' after the interview.
    """

    application_id: uuid.UUID
    employment_type: str = Field("temp", pattern="^(fulltime|parttime|minijob|temp)$")
    max_weekly_hours: int | None = Field(None, ge=1, le=60)
    hourly_rate: Decimal | None = None
    assigned_manager_id: uuid.UUID | None = None
    internal_note: str | None = None


router = APIRouter()


# ── candidate search (for activation flow) ────────────────────────────────────


class CandidateSearchRead(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    model_config = {"from_attributes": True}


@router.get("/search-candidate", response_model=CandidateSearchRead)
async def search_candidate(
    email: str,
    user: TenantRecruiterUser,
    db: DBSession,
) -> CandidateSearchRead:
    """Find a candidate by exact email for the activation drawer."""
    result = await db.execute(select(User).where(User.email == email.lower().strip()))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Kein Nutzer mit dieser E-Mail gefunden.")
    return CandidateSearchRead.model_validate(candidate)


# ── helpers ───────────────────────────────────────────────────────────────────


def _require_same_tenant(user: User, settings: WorkerSettings) -> None:
    if settings.tenant_id != user.tenant_id:
        raise HTTPException(status_code=403, detail="Kein Zugriff auf diesen Worker.")


async def _get_settings_or_404(db: DBSession, user_id: uuid.UUID) -> WorkerSettings:
    result = await db.execute(select(WorkerSettings).where(WorkerSettings.user_id == user_id))
    s = result.scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="Worker-Einstellungen nicht gefunden.")
    return s


def _build_list_row(
    worker: User,
    settings: WorkerSettings | None,
    manager: User | None,
    team: Team | None = None,
) -> WorkerListRead:
    enabled = sum(1 for v in (settings.active_modules or {}).values() if v) if settings else 0
    return WorkerListRead(
        id=worker.id,
        full_name=worker.full_name,
        email=worker.email,
        is_active_user=worker.is_active,
        settings=WorkerSettingsRead.model_validate(settings) if settings else None,
        employment_type=settings.employment_type if settings else None,
        modules_enabled=enabled,
        manager=ManagerRead.model_validate(manager) if manager else None,
        team=TeamSummaryRead(id=team.id, name=team.name) if team else None,
    )


# ── list ──────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[WorkerListRead])
async def list_workers(user: TenantRecruiterUser, db: DBSession) -> list[WorkerListRead]:
    """All workers belonging to this tenant, with their settings."""
    rows = await db.execute(
        select(User, WorkerSettings)
        .outerjoin(WorkerSettings, WorkerSettings.user_id == User.id)
        .where(User.role == "worker")
        .where(WorkerSettings.tenant_id == user.tenant_id)
        .order_by(User.full_name)
    )
    results = rows.all()

    # Resolve managers in one query
    manager_ids = {s.assigned_manager_id for _, s in results if s and s.assigned_manager_id}
    managers: dict[uuid.UUID, User] = {}
    if manager_ids:
        mgr_rows = await db.execute(select(User).where(User.id.in_(manager_ids)))
        managers = {u.id: u for u in mgr_rows.scalars()}

    # Resolve teams in one query
    from app.teams.models import Team

    team_ids = {s.assigned_team_id for _, s in results if s and s.assigned_team_id}
    teams: dict[uuid.UUID, Team] = {}
    if team_ids:
        t_rows = await db.execute(select(Team).where(Team.id.in_(team_ids)))
        teams = {t.id: t for t in t_rows.scalars()}

    return [
        _build_list_row(
            w,
            s,
            managers.get(s.assigned_manager_id) if s and s.assigned_manager_id else None,
            teams.get(s.assigned_team_id) if s and s.assigned_team_id else None,
        )
        for w, s in results
    ]


@router.get("/{worker_id}", response_model=WorkerListRead)
async def get_worker(
    worker_id: uuid.UUID, user: TenantRecruiterUser, db: DBSession
) -> WorkerListRead:
    settings = await _get_settings_or_404(db, worker_id)
    _require_same_tenant(user, settings)

    worker_row = await db.execute(select(User).where(User.id == worker_id))
    worker = worker_row.scalar_one_or_none()
    if not worker:
        raise HTTPException(status_code=404, detail="User nicht gefunden.")

    manager = None
    if settings.assigned_manager_id:
        mgr_row = await db.execute(select(User).where(User.id == settings.assigned_manager_id))
        manager = mgr_row.scalar_one_or_none()

    return _build_list_row(worker, settings, manager)


# ── activate (single) ─────────────────────────────────────────────────────────


@router.post("/activate", response_model=WorkerListRead, status_code=201)
async def activate_worker(
    data: WorkerActivateRequest,
    user: TenantRecruiterUser,
    db: DBSession,
) -> WorkerListRead:
    """Promote a candidate to worker and create their settings in one step."""
    worker_row = await db.execute(select(User).where(User.id == data.user_id))
    worker = worker_row.scalar_one_or_none()
    if not worker:
        raise HTTPException(status_code=404, detail="User nicht gefunden.")

    if worker.role not in {"candidate", "worker"} or worker.tenant_id not in {None, user.tenant_id}:
        raise HTTPException(
            status_code=403,
            detail="Dieser Nutzer kann nicht für diese Organisation aktiviert werden.",
        )
    if data.assigned_manager_id:
        await require_member(db, user.tenant_id, data.assigned_manager_id, ("recruiter", "admin"))

    # Idempotent: if already a worker, just return existing
    existing = await db.execute(
        select(WorkerSettings).where(WorkerSettings.user_id == data.user_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User ist bereits als Worker aktiviert.")

    # Set role
    worker.role = "worker"
    worker.tenant_id = worker.tenant_id or user.tenant_id

    settings = WorkerSettings(
        user_id=data.user_id,
        tenant_id=user.tenant_id,
        is_active=True,
        employment_type=data.employment_type,
        max_weekly_hours=data.max_weekly_hours,
        hourly_rate=data.hourly_rate,
        active_modules=dict(ALL_MODULES),
        internal_note=data.internal_note,
        assigned_manager_id=data.assigned_manager_id or user.id,
        activated_at=datetime.now(),
    )
    db.add(settings)
    await db.commit()
    await db.refresh(settings)
    await db.refresh(worker)

    manager = None
    if settings.assigned_manager_id:
        mgr_row = await db.execute(select(User).where(User.id == settings.assigned_manager_id))
        manager = mgr_row.scalar_one_or_none()

    return _build_list_row(worker, settings, manager)


# ── hire from application (interview → hired → worker) ───────────────────────


@router.post("/hire-from-application", response_model=WorkerListRead, status_code=201)
async def hire_from_application(
    data: HireFromApplicationRequest,
    user: TenantRecruiterUser,
    db: DBSession,
) -> WorkerListRead:
    """Marks an application as 'offer' (hired) and activates the candidate as worker.

    This is the end of the hiring pipeline:
      applied → screening → interview → *hire-from-application* → worker activated

    Idempotent: if the candidate is already a worker, raises 409.
    """
    from app.applications.models import Application, ApplicationHistory, ApplicationStatus

    # Fetch application
    app_row = await db.execute(select(Application).where(Application.id == data.application_id))
    application = app_row.scalar_one_or_none()
    if not application:
        raise HTTPException(status_code=404, detail="Bewerbung nicht gefunden.")

    from app.jobs.models import JobPosting

    job = await db.get(JobPosting, application.job_id) if application.job_id else None
    if job is None or job.tenant_id != user.tenant_id:
        raise HTTPException(
            status_code=404, detail="Bewerbung nicht in dieser Organisation gefunden."
        )
    if data.assigned_manager_id:
        await require_member(db, user.tenant_id, data.assigned_manager_id, ("recruiter", "admin"))

    # Fetch candidate user
    worker_row = await db.execute(select(User).where(User.id == application.user_id))
    worker = worker_row.scalar_one_or_none()
    if not worker:
        raise HTTPException(status_code=404, detail="Kandidat nicht gefunden.")

    if worker.role not in {"candidate", "worker"} or worker.tenant_id not in {None, user.tenant_id}:
        raise HTTPException(
            status_code=403, detail="Person gehört bereits zu einer anderen Organisation."
        )

    # Idempotency check
    existing = await db.execute(select(WorkerSettings).where(WorkerSettings.user_id == worker.id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Kandidat ist bereits als Worker aktiviert.")

    # Advance application to "offer" (= hired for Zeitarbeit context)
    old_status = application.status
    application.status = ApplicationStatus.OFFER
    db.add(
        ApplicationHistory(
            application_id=application.id,
            from_status=old_status,
            to_status=ApplicationStatus.OFFER,
            note=f"Als Zeitarbeiter eingestellt durch {user.full_name or user.email}",
        )
    )

    # Activate as worker
    worker.role = "worker"
    worker.tenant_id = worker.tenant_id or user.tenant_id

    settings = WorkerSettings(
        user_id=worker.id,
        tenant_id=user.tenant_id,
        is_active=True,
        employment_type=data.employment_type,
        max_weekly_hours=data.max_weekly_hours,
        hourly_rate=data.hourly_rate,
        active_modules=dict(ALL_MODULES),
        internal_note=data.internal_note,
        assigned_manager_id=data.assigned_manager_id or user.id,
        activated_at=datetime.now(),
    )
    db.add(settings)
    await db.commit()
    await db.refresh(settings)
    await db.refresh(worker)

    manager = None
    if settings.assigned_manager_id:
        mgr_row = await db.execute(select(User).where(User.id == settings.assigned_manager_id))
        manager = mgr_row.scalar_one_or_none()

    return _build_list_row(worker, settings, manager)


# ── update settings (single) ─────────────────────────────────────────────────


@router.patch("/{worker_id}/settings", response_model=WorkerSettingsRead)
async def update_worker_settings(
    worker_id: uuid.UUID,
    data: WorkerSettingsUpdate,
    user: TenantRecruiterUser,
    db: DBSession,
) -> WorkerSettingsRead:
    """Update any combination of worker settings fields — partial update."""
    settings = await _get_settings_or_404(db, worker_id)
    _require_same_tenant(user, settings)

    if data.assigned_manager_id:
        await require_member(db, user.tenant_id, data.assigned_manager_id, ("recruiter", "admin"))
    if data.assigned_team_id:
        from app.teams.models import Team

        team = await db.get(Team, data.assigned_team_id)
        if team is None or team.tenant_id != user.tenant_id:
            raise HTTPException(status_code=404, detail="Team nicht gefunden.")
    update_data = data.model_dump(exclude_unset=True)
    if "active_modules" in update_data and update_data["active_modules"] is not None:
        # Merge with existing so unknown keys survive
        merged = dict(settings.active_modules or ALL_MODULES)
        merged.update(update_data.pop("active_modules"))
        settings.active_modules = merged

    for field, value in update_data.items():
        setattr(settings, field, value)

    settings.updated_at = datetime.now(UTC).replace(tzinfo=None)
    await db.commit()
    await db.refresh(settings)
    return WorkerSettingsRead.model_validate(settings)


# ── bulk actions ──────────────────────────────────────────────────────────────


@router.post("/bulk", response_model=dict)
async def bulk_action(
    data: WorkerBulkRequest,
    user: TenantRecruiterUser,
    db: DBSession,
) -> dict[str, Any]:
    """
    Bulk operations on multiple workers:
    - activate: set is_active=true
    - deactivate: set is_active=false
    - assign_manager: set assigned_manager_id
    """
    rows = await db.execute(
        select(WorkerSettings)
        .where(WorkerSettings.user_id.in_(data.user_ids))
        .where(WorkerSettings.tenant_id == user.tenant_id)
    )
    settings_list = rows.scalars().all()

    if not settings_list:
        raise HTTPException(status_code=404, detail="Keine Worker gefunden.")

    if data.action == "assign_manager" and data.assigned_manager_id:
        await require_member(db, user.tenant_id, data.assigned_manager_id, ("recruiter", "admin"))

    now = datetime.now(UTC).replace(tzinfo=None)
    affected = 0

    for s in settings_list:
        if data.action == "activate":
            s.is_active = True
        elif data.action == "deactivate":
            s.is_active = False
        elif data.action == "assign_manager":
            if not data.assigned_manager_id:
                raise HTTPException(status_code=422, detail="assigned_manager_id erforderlich.")
            s.assigned_manager_id = data.assigned_manager_id
        s.updated_at = now
        affected += 1

    await db.commit()
    return {"affected": affected, "action": data.action}


# ── deactivate (single shortcut) ─────────────────────────────────────────────


@router.delete("/{worker_id}", status_code=204)
async def deactivate_worker(
    worker_id: uuid.UUID,
    user: TenantRecruiterUser,
    db: DBSession,
) -> None:
    """Soft-deactivate: revoke worker portal access without deleting data."""
    settings = await _get_settings_or_404(db, worker_id)
    _require_same_tenant(user, settings)
    settings.is_active = False
    settings.updated_at = datetime.now(UTC).replace(tzinfo=None)
    await db.commit()
