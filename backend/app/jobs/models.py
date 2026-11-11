"""Job posting models with pgvector embedding – Sprint 0.4."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 output dimension


class JobPosting(Base):
    __tablename__ = "job_postings"
    __table_args__ = (
        CheckConstraint(
            "publication_status IN ('draft', 'published', 'archived')",
            name="ck_job_publication_status",
        ),
        CheckConstraint("version > 0", name="ck_job_version"),
        CheckConstraint(
            "publication_status != 'published' OR (published_at IS NOT NULL AND expires_at IS NOT NULL AND expires_at > published_at)",
            name="ck_job_publication_dates",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Core fields
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Classification
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    required_skills: Mapped[list[Any]] = mapped_column(ARRAY(String), default=list)
    employment_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # full-time|part-time|contract

    # Classification
    category: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    # Recruiter ownership (NULL = scraped/mock job)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Tenant isolation – set when created by a tenant-assigned recruiter
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Source tracking
    source: Mapped[str] = mapped_column(String(100), nullable=False, default="mock")
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)

    # Explicit publication; expiry is checked at read time, independent of a scheduler.
    publication_status: Mapped[str] = mapped_column(
        String(20), default="draft", server_default="draft"
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # pgvector embedding (title + description → sentence-transformers)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    # Timestamps
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relations
    match_scores: Mapped[list[JobMatchScore]] = relationship(
        "JobMatchScore", back_populates="job", cascade="all, delete-orphan"
    )


class JobPublicationEvent(Base):
    """Publication decisions; no request headers, candidate data, or mutable payloads."""

    __tablename__ = "job_publication_events"
    __table_args__ = (UniqueConstraint("job_id", "version", name="uq_job_publication_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_postings.id", ondelete="RESTRICT"), index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SavedJob(Base):
    """Candidate bookmarks a job posting for later review."""

    __tablename__ = "saved_jobs"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_saved_jobs_user_job"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("job_postings.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class JobAlert(Base):
    """Candidate subscribes to matching job notifications."""

    __tablename__ = "job_alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    keywords: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    remote_only: Mapped[bool] = mapped_column(Boolean, default=False)
    min_salary: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    min_score: Mapped[int] = mapped_column(Integer, default=60)  # 0-100
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class JobMatchScore(Base):
    """Cached match score between a candidate profile and a job posting."""

    __tablename__ = "job_match_scores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("job_postings.id", ondelete="CASCADE"),
        nullable=False,
    )

    score: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0–100.0
    vector_similarity: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # cosine similarity
    skill_overlap: Mapped[float | None] = mapped_column(Float, nullable=True)  # % skills matched
    explanation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)  # breakdown

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job: Mapped[JobPosting] = relationship("JobPosting", back_populates="match_scores")
