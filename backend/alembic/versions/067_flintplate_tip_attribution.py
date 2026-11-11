"""Preserve open tip sources and explicitly attribute approved payroll time."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A later run can allocate sources that were still open in an earlier run.
    op.drop_constraint("uq_fp_tip_period", "fp_tip_runs", type_="unique")
    op.create_table(
        "fp_tip_time_attributions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "entry_id", pg.UUID(as_uuid=True), sa.ForeignKey("time_entries.id"), nullable=False
        ),
        sa.Column("shift_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_shifts.id"), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("entry_hash", sa.String(64), nullable=False),
        sa.Column("shift_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("entry_id", "shift_id", name="uq_fp_tip_time_attribution"),
    )
    op.create_index(
        "ix_fp_tip_time_attributions_entry_id", "fp_tip_time_attributions", ["entry_id"]
    )
    op.create_index(
        "ix_fp_tip_time_attributions_shift_id", "fp_tip_time_attributions", ["shift_id"]
    )


def downgrade() -> None:
    # Fail transactionally instead of deleting financial history to satisfy the old schema.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM fp_tip_runs GROUP BY venue_id, "
        "period_start, period_end HAVING count(*) > 1) THEN "
        "RAISE EXCEPTION 'Cannot downgrade tip sources: multiple runs exist for a period'; "
        "END IF; END $$"
    )
    op.create_unique_constraint(
        "uq_fp_tip_period", "fp_tip_runs", ["venue_id", "period_start", "period_end"]
    )
    op.drop_index("ix_fp_tip_time_attributions_shift_id", table_name="fp_tip_time_attributions")
    op.drop_index("ix_fp_tip_time_attributions_entry_id", table_name="fp_tip_time_attributions")
    op.drop_table("fp_tip_time_attributions")
