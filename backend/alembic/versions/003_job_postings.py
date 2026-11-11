"""Job postings + match scores + pgvector index

Revision ID: 003_jobs
Revises: 002_profiles
Create Date: 2026-03-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from alembic import op

revision: str = "003_jobs"
down_revision: str | None = "002_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 384


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "job_postings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("company", sa.String(255), nullable=False),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("url", sa.String(1000), nullable=True),
        sa.Column("is_remote", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("salary_min", sa.Integer, nullable=True),
        sa.Column("salary_max", sa.Integer, nullable=True),
        sa.Column("required_skills", ARRAY(sa.String), nullable=False, server_default="{}"),
        sa.Column("employment_type", sa.String(50), nullable=True),
        sa.Column("source", sa.String(100), nullable=False, server_default="mock"),
        sa.Column("external_id", sa.String(255), nullable=True, unique=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # HNSW index for fast approximate nearest-neighbor search
    op.execute(
        "CREATE INDEX job_postings_embedding_hnsw_idx "
        "ON job_postings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    op.create_table(
        "job_match_scores",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "profile_id",
            UUID(as_uuid=True),
            sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            UUID(as_uuid=True),
            sa.ForeignKey("job_postings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("vector_similarity", sa.Float, nullable=True),
        sa.Column("skill_overlap", sa.Float, nullable=True),
        sa.Column("explanation", JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_index(
        "job_match_scores_profile_job_idx",
        "job_match_scores",
        ["profile_id", "job_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("job_match_scores")
    op.drop_index("job_postings_embedding_hnsw_idx", table_name="job_postings")
    op.drop_table("job_postings")
