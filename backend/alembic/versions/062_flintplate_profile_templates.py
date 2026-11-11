"""Profile templates for staff qualification, with per-person overrides."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fp_profile_templates",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.String(300), nullable=False, server_default=""),
        sa.Column("stations", pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("competence", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("venue_id", "name", name="uq_fp_template_name"),
        sa.CheckConstraint("competence BETWEEN 1 AND 5", name="ck_fp_template_competence"),
    )
    op.create_index("ix_fp_profile_templates_venue_id", "fp_profile_templates", ["venue_id"])
    op.add_column(
        "fp_memberships",
        sa.Column(
            "template_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("fp_profile_templates.id"),
            nullable=True,
        ),
    )
    # Names of the fields a person keeps locally; everything else follows the template.
    op.add_column(
        "fp_memberships",
        sa.Column("overrides", pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("fp_memberships", "overrides")
    op.drop_column("fp_memberships", "template_id")
    op.drop_index("ix_fp_profile_templates_venue_id", table_name="fp_profile_templates")
    op.drop_table("fp_profile_templates")
