"""Job search optimizations: indices, category column, US-job cleanup.

Revision ID: 007_job_optimizations
Revises: 006_feedback
Create Date: 2026-03-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "007_job_optimizations"
down_revision: str | None = "006_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. Remove non-German scraper jobs (imported before Germany filter) ────
    op.execute("""
        DELETE FROM job_postings
        WHERE source LIKE 'scraper:%%'
        AND location IS NOT NULL
        AND (
            lower(location) LIKE '%%united states%%'
            OR lower(location) LIKE '%%usa%%'
            OR lower(location) LIKE '%% usa%%'
            OR lower(location) LIKE '%%new york%%'
            OR lower(location) LIKE '%%san francisco%%'
            OR lower(location) LIKE '%%los angeles%%'
            OR lower(location) LIKE '%%chicago%%'
            OR lower(location) LIKE '%%seattle%%'
            OR lower(location) LIKE '%%london%%'
            OR lower(location) LIKE '%%united kingdom%%'
            OR lower(location) LIKE '%%, uk%%'
            OR lower(location) LIKE '%%canada%%'
            OR lower(location) LIKE '%%australia%%'
            OR lower(location) LIKE '%%india%%'
            OR lower(location) LIKE '%%poland%%'
            OR lower(location) LIKE '%%romania%%'
            OR lower(location) LIKE '%%netherlands%%'
        )
    """)

    # ── 2. Add category column ────────────────────────────────────────────────
    op.add_column("job_postings", sa.Column("category", sa.String(50), nullable=True))

    # ── 3. Standard B-tree indices ────────────────────────────────────────────
    op.execute("CREATE INDEX job_postings_created_at_idx ON job_postings (created_at DESC)")
    op.execute("CREATE INDEX job_postings_is_remote_idx  ON job_postings (is_remote)")
    op.execute("CREATE INDEX job_postings_source_idx     ON job_postings (source)")
    op.execute("CREATE INDEX job_postings_category_idx   ON job_postings (category)")

    # ── 4. GIN index for required_skills array containment/overlap queries ────
    op.execute(
        "CREATE INDEX job_postings_skills_gin_idx " "ON job_postings USING GIN (required_skills)"
    )

    # ── 5. pg_trgm trigram index for fast ILIKE location search ──────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX job_postings_location_trgm_idx "
        "ON job_postings USING GIN (lower(location) gin_trgm_ops)"
    )

    # ── 6. Full-text search index on title ───────────────────────────────────
    op.execute(
        "CREATE INDEX job_postings_title_fts_idx "
        "ON job_postings USING GIN (to_tsvector('simple', title))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS job_postings_title_fts_idx")
    op.execute("DROP INDEX IF EXISTS job_postings_location_trgm_idx")
    op.execute("DROP INDEX IF EXISTS job_postings_skills_gin_idx")
    op.execute("DROP INDEX IF EXISTS job_postings_category_idx")
    op.execute("DROP INDEX IF EXISTS job_postings_source_idx")
    op.execute("DROP INDEX IF EXISTS job_postings_is_remote_idx")
    op.execute("DROP INDEX IF EXISTS job_postings_created_at_idx")
    op.drop_column("job_postings", "category")
