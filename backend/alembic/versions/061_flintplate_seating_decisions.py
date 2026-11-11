"""Resource attributes, seating defaults and recorded decision proposals."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fp_tables",
        sa.Column("tags", pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "fp_tables", sa.Column("min_party", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        "fp_tables",
        sa.Column(
            "combinable_with", pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
    )
    op.create_check_constraint("ck_fp_table_min_party", "fp_tables", "min_party >= 1")
    op.add_column(
        "fp_venues",
        sa.Column("default_stay_minutes", sa.Integer(), nullable=False, server_default="90"),
    )
    op.add_column(
        "fp_venues",
        sa.Column("walkin_hold_seats", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_fp_venue_seating",
        "fp_venues",
        "default_stay_minutes BETWEEN 15 AND 600 AND walkin_hold_seats >= 0",
    )
    op.create_table(
        "fp_decisions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("request", pg.JSONB(), nullable=False),
        sa.Column("options", pg.JSONB(), nullable=False),
        sa.Column("prompt", sa.String(1000), nullable=False, server_default=""),
        # Separate from the prompt text: whether a model actually shaped the weights.
        sa.Column("prompt_applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("engine", sa.String(40), nullable=False),
        sa.Column("chosen_key", sa.String(40), nullable=True),
        sa.Column("chosen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_fp_decisions_venue_id", "fp_decisions", ["venue_id"])
    op.create_table(
        "fp_decision_criteria",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("text", sa.String(1000), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("venue_id", "kind", "label", name="uq_fp_criteria_label"),
    )
    op.create_index("ix_fp_decision_criteria_venue_id", "fp_decision_criteria", ["venue_id"])


def downgrade() -> None:
    # Recorded proposals are history; the downgrade removes the tables entirely
    # rather than pretending a partial rollback keeps them readable.
    op.drop_index("ix_fp_decision_criteria_venue_id", table_name="fp_decision_criteria")
    op.drop_table("fp_decision_criteria")
    op.drop_index("ix_fp_decisions_venue_id", table_name="fp_decisions")
    op.drop_table("fp_decisions")
    op.drop_constraint("ck_fp_venue_seating", "fp_venues", type_="check")
    op.drop_column("fp_venues", "walkin_hold_seats")
    op.drop_column("fp_venues", "default_stay_minutes")
    op.drop_constraint("ck_fp_table_min_party", "fp_tables", type_="check")
    op.drop_column("fp_tables", "combinable_with")
    op.drop_column("fp_tables", "min_party")
    op.drop_column("fp_tables", "tags")
