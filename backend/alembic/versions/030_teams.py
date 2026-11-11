"""030 teams – Team management foundation

Revision ID: 030
Revises: 029
Create Date: 2026-03-27
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None

TEAM_MEMBER_ROLES = ("lead", "member", "viewer")


def upgrade() -> None:
    # ── teams ─────────────────────────────────────────────────────────────────
    op.create_table(
        "teams",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        # Hierarchical: optional parent for regions/branches
        sa.Column(
            "parent_team_id",
            UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_teams_tenant", "teams", ["tenant_id"])

    # ── team_members ──────────────────────────────────────────────────────────
    op.create_table(
        "team_members",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "team_id",
            UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # lead | member | viewer
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
        sa.Column(
            "joined_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Unique: one user can only have one role per team
    op.create_unique_constraint("uq_team_members_team_user", "team_members", ["team_id", "user_id"])

    # ── assigned_team_id on worker_settings ───────────────────────────────────
    op.add_column(
        "worker_settings",
        sa.Column(
            "assigned_team_id",
            UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_worker_settings_team", "worker_settings", ["assigned_team_id"])


def downgrade() -> None:
    op.drop_index("ix_worker_settings_team", "worker_settings")
    op.drop_column("worker_settings", "assigned_team_id")
    op.drop_constraint("uq_team_members_team_user", "team_members", type_="unique")
    op.drop_table("team_members")
    op.drop_index("ix_teams_tenant", "teams")
    op.drop_table("teams")
