"""Authorization for personal templates and organization-scoped applications."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.models import Application
from app.jobs.models import JobPosting
from app.pipeline.models import PipelineStage, PipelineTemplate
from app.users.models import User


async def require_template(
    db: AsyncSession, template_id: UUID, user: User, *, write: bool = False
) -> PipelineTemplate:
    template = await db.scalar(
        select(PipelineTemplate)
        .where(PipelineTemplate.id == template_id)
        .execution_options(populate_existing=True)
    )
    if template is None:
        raise HTTPException(status_code=404, detail="Pipeline nicht gefunden.")
    system = template.recruiter_id is None and template.company_id is None
    own = template.recruiter_id == user.id
    shared = user.company_id is not None and template.company_id == user.company_id
    if not (system or own or shared):
        raise HTTPException(status_code=404, detail="Pipeline nicht gefunden.")
    if system and write:
        raise HTTPException(
            status_code=403, detail="System-Pipelines können nicht bearbeitet werden."
        )
    return template


async def require_stage(
    db: AsyncSession, stage_id: UUID, user: User, *, write: bool = False
) -> PipelineStage:
    stage = await db.get(PipelineStage, stage_id)
    if stage is None:
        raise HTTPException(status_code=404, detail="Stage nicht gefunden.")
    await require_template(db, stage.template_id, user, write=write)
    return stage


async def require_application(db: AsyncSession, application_id: UUID, user: User) -> Application:
    visibility = JobPosting.owner_id == user.id
    if user.tenant_id is not None:
        visibility = visibility | (JobPosting.tenant_id == user.tenant_id)
    application = await db.scalar(
        select(Application)
        .join(JobPosting, JobPosting.id == Application.job_id)
        .where(Application.id == application_id, visibility)
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Bewerbung nicht gefunden.")
    return application
