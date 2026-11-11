"""025 org_charts – Organigramm-Feature

Revision ID: 025
Revises: 024
Create Date: 2026-03-26
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── org_charts ────────────────────────────────────────────────────────────
    op.create_table(
        "org_charts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        # hierarchical | matrix | flat | divisional
        sa.Column("chart_type", sa.String(50), nullable=False, server_default="hierarchical"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # ── org_nodes ─────────────────────────────────────────────────────────────
    op.create_table(
        "org_nodes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "chart_id",
            UUID(as_uuid=True),
            sa.ForeignKey("org_charts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "person_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(255), nullable=False),  # Position title
        sa.Column("department", sa.String(100), nullable=True),
        sa.Column("person_name", sa.String(255), nullable=True),  # freetext if no user assigned
        sa.Column("person_email", sa.String(255), nullable=True),
        # filled | open | temp | contractor | planned
        sa.Column("status", sa.String(50), nullable=False, server_default="open"),
        sa.Column("pos_x", sa.Float, nullable=False, server_default="0"),
        sa.Column("pos_y", sa.Float, nullable=False, server_default="0"),
        sa.Column("node_width", sa.Float, nullable=False, server_default="200"),
        sa.Column("node_height", sa.Float, nullable=False, server_default="80"),
        sa.Column("color", sa.String(7), nullable=True),  # dept override color
        sa.Column(
            "job_posting_id",
            UUID(as_uuid=True),
            sa.ForeignKey("job_postings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("metadata", JSONB, nullable=True),  # salary_band, location, etc.
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # ── org_edges ─────────────────────────────────────────────────────────────
    op.create_table(
        "org_edges",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "chart_id",
            UUID(as_uuid=True),
            sa.ForeignKey("org_charts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "source_id",
            UUID(as_uuid=True),
            sa.ForeignKey("org_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_id",
            UUID(as_uuid=True),
            sa.ForeignKey("org_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # solid | dotted | functional
        sa.Column("edge_type", sa.String(50), nullable=False, server_default="solid"),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_org_edges_source", "org_edges", ["source_id"])
    op.create_index("ix_org_edges_target", "org_edges", ["target_id"])


def downgrade() -> None:
    op.drop_table("org_edges")
    op.drop_table("org_nodes")
    op.drop_table("org_charts")
