"""Vermerke service layer."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.vermerke.models import Vermerk
from app.vermerke.schemas import VermerkCreate, VermerkUpdate


def _visibility_filter(visibility: str) -> list[str]:
    """Return allowed visibility values for a given viewer role."""
    if visibility == "internal":
        return ["internal", "partner", "public"]
    if visibility == "partner":
        return ["partner", "public"]
    return ["public"]


async def create_vermerk(
    db: AsyncSession,
    author_id: uuid.UUID,
    data: VermerkCreate,
) -> Vermerk:
    targets = [data.candidate_id, data.application_id, data.assignment_id]
    set_targets = [t for t in targets if t is not None]
    if len(set_targets) != 1:
        raise ValueError(
            "Genau eines von candidate_id, application_id, assignment_id muss gesetzt sein."
        )

    vermerk = Vermerk(
        author_id=author_id,
        candidate_id=data.candidate_id,
        application_id=data.application_id,
        assignment_id=data.assignment_id,
        type=data.type,
        text=data.text,
        visibility=data.visibility,
        valid_until=data.valid_until,
        strength=data.strength,
        source=data.source or "manual",
    )
    db.add(vermerk)
    await db.commit()
    await db.refresh(vermerk)
    return vermerk


async def list_for_candidate(
    db: AsyncSession,
    candidate_id: uuid.UUID,
    max_visibility: str = "internal",
) -> list[Vermerk]:
    allowed = _visibility_filter(max_visibility)
    result = await db.execute(
        select(Vermerk)
        .where(
            Vermerk.candidate_id == candidate_id,
            Vermerk.is_active.is_(True),
            Vermerk.visibility.in_(allowed),
        )
        .order_by(Vermerk.created_at.desc())
    )
    return list(result.scalars().all())


async def list_for_application(
    db: AsyncSession,
    application_id: uuid.UUID,
    max_visibility: str = "internal",
) -> list[Vermerk]:
    allowed = _visibility_filter(max_visibility)
    result = await db.execute(
        select(Vermerk)
        .where(
            Vermerk.application_id == application_id,
            Vermerk.is_active.is_(True),
            Vermerk.visibility.in_(allowed),
        )
        .order_by(Vermerk.created_at.desc())
    )
    return list(result.scalars().all())


async def list_for_assignment(
    db: AsyncSession,
    assignment_id: uuid.UUID,
    max_visibility: str = "internal",
) -> list[Vermerk]:
    allowed = _visibility_filter(max_visibility)
    result = await db.execute(
        select(Vermerk)
        .where(
            Vermerk.assignment_id == assignment_id,
            Vermerk.is_active.is_(True),
            Vermerk.visibility.in_(allowed),
        )
        .order_by(Vermerk.created_at.desc())
    )
    return list(result.scalars().all())


async def get_vermerk(db: AsyncSession, vermerk_id: uuid.UUID) -> Vermerk | None:
    result = await db.execute(select(Vermerk).where(Vermerk.id == vermerk_id))
    return result.scalar_one_or_none()


async def update_vermerk(
    db: AsyncSession,
    vermerk: Vermerk,
    data: VermerkUpdate,
) -> Vermerk:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(vermerk, field, value)
    await db.commit()
    await db.refresh(vermerk)
    return vermerk


async def delete_vermerk(db: AsyncSession, vermerk: Vermerk) -> None:
    vermerk.is_active = False
    await db.commit()
