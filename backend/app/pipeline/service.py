"""Pipeline Builder service – palmscout MVP 2."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.pipeline.models import (
    ApplicationStageAssignment,
    ApplicationStageHistory,
    PipelineStage,
    PipelineTemplate,
)
from app.pipeline.schemas import (
    KanbanBoardRead,
    PipelineStageCreate,
    PipelineStageRead,
    PipelineStageUpdate,
    PipelineTemplateCreate,
    PipelineTemplateRead,
    PipelineTemplateUpdate,
    StageTransitionRequest,
    StageTransitionResponse,
)

# ── System default template (seeded in migration 016) ─────────────────────────
SYSTEM_RECRUITER_ID = None  # NULL = system-owned


async def _commit(db: AsyncSession) -> None:
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Die Pipeline wird noch verwendet oder eine Stage-Position ist bereits belegt.",
        ) from None


# ── Templates ─────────────────────────────────────────────────────────────────


async def create_template(
    db: AsyncSession,
    recruiter_id: uuid.UUID,
    data: PipelineTemplateCreate,
) -> PipelineTemplateRead:
    template = PipelineTemplate(
        recruiter_id=recruiter_id,
        name=data.name,
        is_default=False,
    )
    db.add(template)
    await db.flush()  # get template.id before adding stages

    for stage_data in data.stages:
        stage = PipelineStage(template_id=template.id, **stage_data.model_dump())
        db.add(stage)

    await _commit(db)
    await db.refresh(template)
    return PipelineTemplateRead.model_validate(template)


async def list_templates(
    db: AsyncSession,
    recruiter_id: uuid.UUID,
    company_id: uuid.UUID | None = None,
) -> list[PipelineTemplateRead]:
    visibility = (PipelineTemplate.recruiter_id == recruiter_id) | and_(
        PipelineTemplate.recruiter_id.is_(None), PipelineTemplate.company_id.is_(None)
    )
    if company_id is not None:
        visibility = visibility | (PipelineTemplate.company_id == company_id)
    result = await db.execute(
        select(PipelineTemplate)
        .where(visibility)
        .order_by(PipelineTemplate.is_default.desc(), PipelineTemplate.created_at)
    )
    return [PipelineTemplateRead.model_validate(t) for t in result.scalars().all()]


async def get_template(
    db: AsyncSession,
    template_id: uuid.UUID,
) -> PipelineTemplate | None:
    result = await db.execute(
        select(PipelineTemplate)
        .where(PipelineTemplate.id == template_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def update_template(
    db: AsyncSession,
    template: PipelineTemplate,
    data: PipelineTemplateUpdate,
) -> PipelineTemplateRead:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(template, field, value)
    await _commit(db)
    await db.refresh(template)
    return PipelineTemplateRead.model_validate(template)


async def delete_template(db: AsyncSession, template: PipelineTemplate) -> None:
    await db.delete(template)
    await _commit(db)


# ── Stages ────────────────────────────────────────────────────────────────────


async def add_stage(
    db: AsyncSession,
    template_id: uuid.UUID,
    data: PipelineStageCreate,
) -> PipelineStageRead:
    stage = PipelineStage(template_id=template_id, **data.model_dump())
    db.add(stage)
    await _commit(db)
    await db.refresh(stage)
    return PipelineStageRead.model_validate(stage)


async def get_stage(db: AsyncSession, stage_id: uuid.UUID) -> PipelineStage | None:
    return await db.get(PipelineStage, stage_id)


async def update_stage(
    db: AsyncSession,
    stage: PipelineStage,
    data: PipelineStageUpdate,
) -> PipelineStageRead:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(stage, field, value)
    await _commit(db)
    await db.refresh(stage)
    return PipelineStageRead.model_validate(stage)


async def delete_stage(db: AsyncSession, stage: PipelineStage) -> None:
    await db.delete(stage)
    await _commit(db)


# ── Transitions ───────────────────────────────────────────────────────────────


async def get_current_stage(
    db: AsyncSession,
    application_id: uuid.UUID,
) -> PipelineStageRead | None:
    result = await db.execute(
        select(ApplicationStageAssignment).where(
            ApplicationStageAssignment.application_id == application_id
        )
    )
    asa = result.scalar_one_or_none()
    if not asa:
        return None
    stage = await db.get(PipelineStage, asa.stage_id)
    return PipelineStageRead.model_validate(stage) if stage else None


async def transition_stage(
    db: AsyncSession,
    data: StageTransitionRequest,
    changed_by: uuid.UUID,
) -> StageTransitionResponse:
    from app.applications.models import Application

    stage = await db.get(PipelineStage, data.to_stage_id)
    if stage is None:
        raise ValueError("Stage nicht gefunden.")
    # Serialize transitions for the same application, including its first assignment.
    application = await db.scalar(
        select(Application).where(Application.id == data.application_id).with_for_update()
    )
    if application is None:
        raise ValueError("Bewerbung nicht gefunden.")
    # Get or create stage assignment
    result = await db.execute(
        select(ApplicationStageAssignment).where(
            ApplicationStageAssignment.application_id == data.application_id
        )
    )
    asa = result.scalar_one_or_none()

    from_stage_id = asa.stage_id if asa else None

    if asa is None:
        asa = ApplicationStageAssignment(
            application_id=data.application_id,
            stage_id=data.to_stage_id,
        )
        db.add(asa)
    else:
        asa.stage_id = data.to_stage_id
        asa.entered_at = datetime.now(UTC)

    # Log history
    history = ApplicationStageHistory(
        application_id=data.application_id,
        from_stage_id=from_stage_id,
        to_stage_id=data.to_stage_id,
        note=data.note,
        changed_by=changed_by,
    )
    db.add(history)

    # Persist the transition and its notifications together.
    if stage.on_enter_actions:
        await _fire_actions(db, data.application_id, stage.on_enter_actions)
    await _commit(db)
    await db.refresh(asa)

    return StageTransitionResponse(
        application_id=data.application_id,
        stage=PipelineStageRead.model_validate(stage),
    )


async def get_kanban_board(
    db: AsyncSession,
    template_id: uuid.UUID,
    *,
    recruiter_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
) -> KanbanBoardRead:
    """Return all stages with their assigned applications as a Kanban board."""
    from app.applications.models import Application
    from app.jobs.models import JobPosting
    from app.pipeline.schemas import KanbanBoardRead, KanbanCard, KanbanColumn
    from app.users.models import User

    template = await get_template(db, template_id)
    if not template:
        raise ValueError("Template nicht gefunden.")

    columns: list[KanbanColumn] = []
    for stage in sorted(template.stages, key=lambda s: s.position):
        # Load all applications in this stage
        assignments_result = await db.execute(
            select(ApplicationStageAssignment).where(
                ApplicationStageAssignment.stage_id == stage.id
            )
        )
        assignments = assignments_result.scalars().all()

        cards: list[KanbanCard] = []
        for asa in assignments:
            app_result = await db.execute(
                select(Application)
                .join(JobPosting, JobPosting.id == Application.job_id)
                .where(
                    Application.id == asa.application_id,
                    (
                        (JobPosting.owner_id == recruiter_id) | (JobPosting.tenant_id == tenant_id)
                        if tenant_id is not None
                        else JobPosting.owner_id == recruiter_id
                    ),
                )
            )
            app = app_result.scalar_one_or_none()
            if not app:
                continue

            # Get candidate name
            user_result = await db.execute(select(User).where(User.id == app.user_id))
            user = user_result.scalar_one_or_none()

            # Get job title
            job_title = app.position or ""
            company = app.company or ""
            if app.job_id:
                job_result = await db.execute(select(JobPosting).where(JobPosting.id == app.job_id))
                job = job_result.scalar_one_or_none()
                if job:
                    job_title = job.title
                    company = job.company

            cards.append(
                KanbanCard(
                    application_id=asa.application_id,
                    candidate_name=user.full_name if user else None,
                    candidate_email=user.email if user else "",
                    job_title=job_title,
                    company=company,
                    status=app.status,
                    entered_at=asa.entered_at,
                )
            )

        columns.append(
            KanbanColumn(
                stage_id=stage.id,
                stage_name=stage.name,
                stage_color=stage.color,
                position=stage.position,
                is_terminal=stage.is_terminal,
                cards=cards,
            )
        )

    return KanbanBoardRead(
        template_id=template.id,
        template_name=template.name,
        columns=columns,
    )


async def get_stage_history(
    db: AsyncSession,
    application_id: uuid.UUID,
) -> list[ApplicationStageHistory]:
    result = await db.execute(
        select(ApplicationStageHistory)
        .where(ApplicationStageHistory.application_id == application_id)
        .order_by(ApplicationStageHistory.changed_at.desc())
    )
    return list(result.scalars().all())


# ── SLA check (called by scheduler) ───────────────────────────────────────────


async def check_sla_breaches(db: AsyncSession) -> list[uuid.UUID]:
    """SLA-Überprüfung: Benachrichtigung wenn Stage-Verweildauer überschritten."""
    from datetime import timedelta

    from app.applications.models import Application
    from app.jobs.models import JobPosting

    now = datetime.now(UTC)
    breached: list[uuid.UUID] = []

    result = await db.execute(
        select(ApplicationStageAssignment, PipelineStage, Application, JobPosting)
        .join(PipelineStage, ApplicationStageAssignment.stage_id == PipelineStage.id)
        .join(Application, ApplicationStageAssignment.application_id == Application.id)
        .outerjoin(JobPosting, Application.job_id == JobPosting.id)
        .where(PipelineStage.sla_hours.is_not(None))
    )
    rows = result.all()

    for asa, stage, app, job in rows:
        deadline = asa.entered_at + timedelta(hours=stage.sla_hours)
        if now <= deadline:
            continue
        breached.append(asa.application_id)
        recruiter_id = job.owner_id if job else None
        if recruiter_id is None:
            continue
        try:
            from app.notifications.service import create_notification

            await create_notification(
                db,
                user_id=recruiter_id,
                title=f"SLA überschritten: {stage.name}",
                body=(
                    f"Bewerbung {app.position!r} ist seit über {stage.sla_hours}h "
                    f"in Stage '{stage.name}' ohne Fortschritt."
                ),
                type_=stage.sla_escalate_to or "pipeline_sla",
            )
        except Exception:
            pass  # SLA check is best-effort

    return breached


async def _fire_actions(
    db: AsyncSession,
    application_id: uuid.UUID,
    actions: list[dict[str, Any]],
) -> None:
    """Trigger-Aktionen beim Stage-Eintritt ausführen (best-effort)."""
    from app.applications.models import Application
    from app.jobs.models import JobPosting

    application = await db.get(Application, application_id)
    job = (
        await db.get(JobPosting, application.job_id) if application and application.job_id else None
    )
    if job is None or job.owner_id is None:
        return
    for action in actions:
        action_type = action.get("type")
        try:
            if action_type == "notification":
                from app.notifications.service import create_notification

                await create_notification(
                    db,
                    user_id=job.owner_id,
                    title=action.get("title", "Pipeline-Update"),
                    body=action.get("body", f"Bewerbung {application_id} hat Stage gewechselt."),
                    type_="pipeline_trigger",
                )
        except Exception:
            pass
