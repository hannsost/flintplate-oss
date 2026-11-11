"""Candidate profiles: candidate_profiles, work_experiences, educations, skills

Revision ID: 002_profiles
Revises: 001_initial
Create Date: 2026-03-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "002_profiles"
down_revision: str | None = "001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("headline", sa.String(255), nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("linkedin_url", sa.String(500), nullable=True),
        sa.Column("cv_file_path", sa.String(1000), nullable=True),
        sa.Column("cv_original_filename", sa.String(255), nullable=True),
        sa.Column("raw_cv_text", JSONB, nullable=True),
        sa.Column("structured_data", JSONB, nullable=True),
        sa.Column("completeness_score", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP, nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_candidate_profiles_id", "candidate_profiles", ["id"])
    op.create_index("ix_candidate_profiles_user_id", "candidate_profiles", ["user_id"], unique=True)

    op.create_table(
        "work_experiences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "profile_id",
            UUID(as_uuid=True),
            sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("company", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("start_date", sa.Date, nullable=True),
        sa.Column("end_date", sa.Date, nullable=True),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP, nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_work_experiences_id", "work_experiences", ["id"])
    op.create_index("ix_work_experiences_profile_id", "work_experiences", ["profile_id"])

    op.create_table(
        "educations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "profile_id",
            UUID(as_uuid=True),
            sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("institution", sa.String(255), nullable=False),
        sa.Column("degree", sa.String(255), nullable=True),
        sa.Column("field_of_study", sa.String(255), nullable=True),
        sa.Column("start_date", sa.Date, nullable=True),
        sa.Column("end_date", sa.Date, nullable=True),
        sa.Column("grade", sa.String(50), nullable=True),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP, nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_educations_id", "educations", ["id"])
    op.create_index("ix_educations_profile_id", "educations", ["profile_id"])

    op.create_table(
        "skills",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "profile_id",
            UUID(as_uuid=True),
            sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("level", sa.String(50), nullable=True),
        sa.Column("years_of_experience", sa.Integer, nullable=True),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP, nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_skills_id", "skills", ["id"])
    op.create_index("ix_skills_profile_id", "skills", ["profile_id"])
    op.create_index("ix_skills_name", "skills", ["name"])


def downgrade() -> None:
    op.drop_table("skills")
    op.drop_table("educations")
    op.drop_table("work_experiences")
    op.drop_table("candidate_profiles")
