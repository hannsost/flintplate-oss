"""Candidate visibility based on employment or an existing application."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import ColumnElement, select

from app.applications.models import Application
from app.jobs.models import JobPosting
from app.users.models import User


def candidate_visibility(recruiter_id: UUID, tenant_id: UUID | None) -> ColumnElement[bool]:
    jobs: ColumnElement[bool] = (JobPosting.owner_id == recruiter_id) & JobPosting.tenant_id.is_(
        None
    )
    if tenant_id is not None:
        jobs = JobPosting.tenant_id == tenant_id
    visible = (
        select(Application.id)
        .join(JobPosting, JobPosting.id == Application.job_id)
        .where(Application.user_id == User.id, jobs)
        .correlate(User)
        .exists()
    )
    scope: ColumnElement[bool] = visible
    if tenant_id is not None:
        scope = scope | (User.tenant_id == tenant_id)
    return User.is_active.is_(True) & User.role.in_(["candidate", "worker"]) & scope
