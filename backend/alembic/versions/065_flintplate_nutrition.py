"""Dietary markers per venue and the markers a guest carries."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fp_diet_markers",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        # Health, pregnancy and belief are special categories and need consent.
        sa.Column("special", sa.Boolean(), nullable=False, server_default=sa.false()),
        # A legal prohibition refuses the order; everything else warns and can be overruled.
        sa.Column("legal_block", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("avoid", pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("note", sa.String(300), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("venue_id", "key", name="uq_fp_marker_key"),
        sa.CheckConstraint("kind IN ('allergie','diaet','zustand')", name="ck_fp_marker_kind"),
    )
    op.create_index("ix_fp_diet_markers_venue_id", "fp_diet_markers", ["venue_id"])
    op.add_column(
        "fp_guest_profiles",
        sa.Column("markers", pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("fp_guest_profiles", "markers")
    op.drop_index("ix_fp_diet_markers_venue_id", table_name="fp_diet_markers")
    op.drop_table("fp_diet_markers")
