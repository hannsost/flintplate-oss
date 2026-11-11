"""Partner placement service – commission tracking."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.models import Application
from app.jobs.models import JobPosting
from app.placements.models import PartnerPlacement
from app.placements.schemas import PlacementCreate, PlacementRead, PlacementStats
from app.users.models import User


async def mark_as_placed(
    db: AsyncSession,
    recruiter_id: uuid.UUID,
    application_id: uuid.UUID,
    data: PlacementCreate,
) -> PlacementRead:
    """Record a successful placement for an application."""
    # Load application + related data
    app_row = await db.get(Application, application_id)
    if app_row is None:
        raise ValueError("Application not found")

    # Candidate name
    candidate = await db.get(User, app_row.user_id)
    candidate_name = candidate.full_name if candidate else None

    # Job / company info
    job_row: JobPosting | None = None
    if app_row.job_id:
        job_row = await db.get(JobPosting, app_row.job_id)

    position_title = (job_row.title if job_row else None) or app_row.position
    company_name = (job_row.company if job_row else None) or app_row.company

    # Commission calculation
    commission_eur: Decimal | None = None
    if data.annual_salary:
        commission_eur = (
            Decimal(data.annual_salary) * data.commission_pct / Decimal("100")
        ).quantize(Decimal("0.01"))

    placement = PartnerPlacement(
        job_id=app_row.job_id,
        application_id=application_id,
        recruiter_id=recruiter_id,
        candidate_name=candidate_name,
        position_title=position_title,
        company_name=company_name,
        commission_pct=data.commission_pct,
        annual_salary=data.annual_salary,
        commission_eur=commission_eur,
        notes=data.notes,
        placed_at=datetime.now(UTC),
    )
    db.add(placement)
    await db.commit()
    await db.refresh(placement)
    return PlacementRead.model_validate(placement)


async def get_my_placements(
    db: AsyncSession,
    recruiter_id: uuid.UUID,
) -> list[PlacementRead]:
    result = await db.execute(
        select(PartnerPlacement)
        .where(PartnerPlacement.recruiter_id == recruiter_id)
        .order_by(PartnerPlacement.placed_at.desc())
    )
    rows = result.scalars().all()
    return [PlacementRead.model_validate(r) for r in rows]


async def get_placement_stats(
    db: AsyncSession,
    recruiter_id: uuid.UUID,
) -> PlacementStats:
    now = datetime.now(UTC)

    # All-time aggregates
    all_result = await db.execute(
        select(
            func.count(PartnerPlacement.id),
            func.coalesce(func.sum(PartnerPlacement.commission_eur), 0),
            func.coalesce(func.avg(PartnerPlacement.commission_eur), 0),
            func.coalesce(func.avg(PartnerPlacement.commission_pct), Decimal("27.50")),
        ).where(PartnerPlacement.recruiter_id == recruiter_id)
    )
    total, total_eur, avg_eur, avg_pct = all_result.one()

    # This-month aggregates
    month_result = await db.execute(
        select(
            func.count(PartnerPlacement.id),
            func.coalesce(func.sum(PartnerPlacement.commission_eur), 0),
        ).where(
            PartnerPlacement.recruiter_id == recruiter_id,
            extract("year", PartnerPlacement.placed_at) == now.year,
            extract("month", PartnerPlacement.placed_at) == now.month,
        )
    )
    month_count, month_eur = month_result.one()

    return PlacementStats(
        total_placements=int(total),
        total_commission_eur=Decimal(str(total_eur)).quantize(Decimal("0.01")),
        avg_commission_eur=Decimal(str(avg_eur)).quantize(Decimal("0.01")),
        avg_commission_pct=Decimal(str(avg_pct)).quantize(Decimal("0.01")),
        placements_this_month=int(month_count),
        commission_this_month=Decimal(str(month_eur)).quantize(Decimal("0.01")),
    )
