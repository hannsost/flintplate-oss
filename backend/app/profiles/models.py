"""SQLAlchemy 2.0 models for candidate profiles – Sprint 0.2."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import UUID, Boolean, Date, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base_model import UUIDBase


class CandidateProfile(UUIDBase):
    __tablename__ = "candidate_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # Personal info
    is_public: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    headline: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # CV file reference (local Phase 0, S3 key Phase 1+)
    cv_file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cv_original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Raw + AI-structured CV data (JSONB for flexible schema)
    raw_cv_text: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    structured_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Profile completeness (0–100)
    completeness_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    work_experiences: Mapped[list[WorkExperience]] = relationship(
        "WorkExperience",
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="WorkExperience.start_date.desc()",
        lazy="selectin",
    )
    educations: Mapped[list[Education]] = relationship(
        "Education",
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="Education.start_date.desc()",
        lazy="selectin",
    )
    skills: Mapped[list[Skill]] = relationship(
        "Skill",
        back_populates="profile",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class WorkExperience(UUIDBase):
    __tablename__ = "work_experiences"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # None = current
    is_current: Mapped[bool] = mapped_column(default=False, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Trust-Layer: Quelle der Information (z.B. "cv_page_2", "manual")
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)

    profile: Mapped[CandidateProfile] = relationship(
        "CandidateProfile", back_populates="work_experiences"
    )


class Education(UUIDBase):
    __tablename__ = "educations"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    institution: Mapped[str] = mapped_column(String(255), nullable=False)
    degree: Mapped[str | None] = mapped_column(String(255), nullable=True)
    field_of_study: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    grade: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)

    profile: Mapped[CandidateProfile] = relationship(
        "CandidateProfile", back_populates="educations"
    )


class Skill(UUIDBase):
    __tablename__ = "skills"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # beginner / intermediate / advanced / expert
    level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    years_of_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)

    profile: Mapped[CandidateProfile] = relationship("CandidateProfile", back_populates="skills")
