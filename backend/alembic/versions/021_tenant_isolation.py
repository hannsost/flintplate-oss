"""021 tenant isolation – Admin Hub

Creates:
  - customers table (Tenant-Registry)
  - customer_modules table (Feature-Flags)

Adds tenant_id FK to:
  - users
  - job_postings
  - work_assignments
  - interview_schedules
  - interview_scorecards

Enables PostgreSQL Row-Level Security on tenant-scoped tables.

Revision ID: 021
Revises: 020
Create Date: 2026-03-26
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. customers ──────────────────────────────────────────────────────────
    op.create_table(
        "customers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("type", sa.String(50), nullable=False, server_default="recruiter_agency"),
        sa.Column("plan", sa.String(50), nullable=False, server_default="starter"),
        sa.Column("status", sa.String(50), nullable=False, server_default="trial"),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("country", sa.String(2), nullable=False, server_default="DE"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("contract_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("contract_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_customers_slug", "customers", ["slug"])

    # ── 2. customer_modules ───────────────────────────────────────────────────
    op.create_table(
        "customer_modules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("module_key", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("usage_limit", sa.Integer, nullable=True),
        sa.Column("usage_current", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "activated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("customer_id", "module_key", name="uq_customer_module"),
    )

    # ── 3. Add tenant_id to users ─────────────────────────────────────────────
    op.add_column(
        "users",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    # ── 4. Add tenant_id to job_postings ──────────────────────────────────────
    op.add_column(
        "job_postings",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_job_postings_tenant_id", "job_postings", ["tenant_id"])

    # ── 5. Add tenant_id to work_assignments ──────────────────────────────────
    op.add_column(
        "work_assignments",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_work_assignments_tenant_id", "work_assignments", ["tenant_id"])

    # ── 6. Add tenant_id to interview_schedules ───────────────────────────────
    op.add_column(
        "interview_schedules",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_interview_schedules_tenant_id", "interview_schedules", ["tenant_id"])

    # ── 7. Add tenant_id to interview_scorecards ──────────────────────────────
    op.add_column(
        "interview_scorecards",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_interview_scorecards_tenant_id", "interview_scorecards", ["tenant_id"])

    # ── 8. Row-Level Security ─────────────────────────────────────────────────
    # Policy logic:
    #   - tenant_id IS NULL  → legacy / public data (visible to all authenticated users)
    #   - tenant_id IS SET   → only visible when RLS context matches OR user is admin
    #   - app.is_admin = 'true' → bypass all tenant checks

    _rls_policy = """
        (tenant_id IS NULL)
        OR (current_setting('app.is_admin', true) = 'true')
        OR (
            tenant_id::text = current_setting('app.current_tenant_id', true)
            AND current_setting('app.current_tenant_id', true) <> ''
        )
    """

    for table in (
        "job_postings",
        "work_assignments",
        "interview_schedules",
        "interview_scorecards",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} " f"USING ({_rls_policy})")
        # Superuser / table owner bypasses RLS by default; grant access via policy only
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in (
        "job_postings",
        "work_assignments",
        "interview_schedules",
        "interview_scorecards",
    ):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    for table_col in [
        ("interview_scorecards", "ix_interview_scorecards_tenant_id"),
        ("interview_schedules", "ix_interview_schedules_tenant_id"),
        ("work_assignments", "ix_work_assignments_tenant_id"),
        ("job_postings", "ix_job_postings_tenant_id"),
        ("users", "ix_users_tenant_id"),
    ]:
        op.drop_index(table_col[1], table_name=table_col[0])
        op.drop_column(table_col[0], "tenant_id")

    op.drop_table("customer_modules")
    op.drop_table("customers")
