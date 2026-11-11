"""Profile business logic – Sprint 0.2."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.profiles.models import CandidateProfile, Education, Skill, WorkExperience
from app.profiles.schemas import ProfileCreate, ProfileUpdate

_LEVEL_MAP = {
    # English
    "beginner": "beginner",
    "junior": "beginner",
    "basic": "beginner",
    "entry": "beginner",
    "intermediate": "intermediate",
    "mid": "intermediate",
    "middle": "intermediate",
    "advanced": "advanced",
    "senior": "advanced",
    "proficient": "advanced",
    "expert": "expert",
    "principal": "expert",
    "lead": "expert",
    # German
    "anfaenger": "beginner",
    "grundkenntnisse": "beginner",
    "einsteiger": "beginner",
    "fortgeschritten": "advanced",
    "erfahren": "advanced",
    "experte": "expert",
    "spezialist": "expert",
}


def _normalize_level(level: str | None) -> str | None:
    if not level:
        return None
    key = level.lower().strip().replace("ä", "a").replace("ö", "o").replace("ü", "u")
    return _LEVEL_MAP.get(key)  # unknown → null rather than invalid string


def _with_relations(stmt: Select[tuple[CandidateProfile]]) -> Select[tuple[CandidateProfile]]:
    return stmt.options(
        selectinload(CandidateProfile.work_experiences),
        selectinload(CandidateProfile.educations),
        selectinload(CandidateProfile.skills),
    )


async def get_or_create_profile(db: AsyncSession, user_id: uuid.UUID) -> CandidateProfile:
    """Return existing profile or create a blank one."""
    result = await db.execute(
        _with_relations(select(CandidateProfile).where(CandidateProfile.user_id == user_id))
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = CandidateProfile(user_id=user_id)
        db.add(profile)
        await db.flush()
        await db.refresh(profile, ["work_experiences", "educations", "skills"])
    return profile


async def get_profile_by_id(db: AsyncSession, profile_id: uuid.UUID) -> CandidateProfile:
    result = await db.execute(
        _with_relations(select(CandidateProfile).where(CandidateProfile.id == profile_id))
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profil nicht gefunden")
    return profile


async def create_profile(
    db: AsyncSession, user_id: uuid.UUID, data: ProfileCreate
) -> CandidateProfile:
    existing = await db.execute(
        _with_relations(select(CandidateProfile).where(CandidateProfile.user_id == user_id))
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Profil existiert bereits. Verwende PATCH /profiles/me zum Aktualisieren.",
        )
    profile = CandidateProfile(user_id=user_id, **data.model_dump(exclude_none=True))
    db.add(profile)
    await db.flush()
    await db.refresh(profile, ["work_experiences", "educations", "skills"])
    return profile


async def update_profile(
    db: AsyncSession,
    profile: CandidateProfile,
    data: ProfileUpdate,
) -> CandidateProfile:
    update_data = data.model_dump(
        exclude_none=True, exclude={"work_experiences", "educations", "skills"}
    )
    for field, value in update_data.items():
        setattr(profile, field, value)

    # Ensure collections are loaded before iterating
    await db.refresh(profile, ["work_experiences", "educations", "skills"])

    # Replace sub-collections if provided
    if data.work_experiences is not None:
        for we in list(profile.work_experiences):
            await db.delete(we)
        for we_data in data.work_experiences:
            db.add(WorkExperience(profile_id=profile.id, **we_data.model_dump()))

    if data.educations is not None:
        for ed in list(profile.educations):
            await db.delete(ed)
        for ed_data in data.educations:
            db.add(Education(profile_id=profile.id, **ed_data.model_dump()))

    if data.skills is not None:
        for sk in list(profile.skills):
            await db.delete(sk)
        for sk_data in data.skills:
            sk_dict = sk_data.model_dump()
            sk_dict["level"] = _normalize_level(sk_dict.get("level"))
            db.add(Skill(profile_id=profile.id, **sk_dict))

    await db.flush()
    await db.refresh(profile)
    await db.refresh(profile, ["work_experiences", "educations", "skills"])
    _update_completeness(profile)
    return profile


def _update_completeness(profile: CandidateProfile) -> None:
    """Simple heuristic: count filled fields (0–100)."""
    score = 0
    if profile.headline:
        score += 15
    if profile.summary:
        score += 15
    if profile.location:
        score += 10
    if profile.phone:
        score += 5
    if profile.cv_file_path:
        score += 20
    if profile.work_experiences:
        score += 20
    if profile.educations:
        score += 10
    if profile.skills:
        score += 5
    profile.completeness_score = min(score, 100)
