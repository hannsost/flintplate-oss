"""Versioned operational hygiene plans and immutable check attribution."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "075"
down_revision = "074"
branch_labels = None
depends_on = None


def base() -> list[sa.Column]:
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("request_key", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
    ]


def upgrade() -> None:
    op.create_unique_constraint("uq_fp_haccp_record_scope", "fp_haccp_records", ["venue_id", "id"])
    op.create_table(
        "fp_hygiene_plan_versions",
        *base(),
        sa.Column("plan_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("data", pg.JSONB(), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_hygiene_plan_scope"),
        sa.UniqueConstraint("venue_id", "plan_id", "version", name="uq_fp_hygiene_plan_version"),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_hygiene_plan_request"),
    )
    op.create_index("ix_fp_hygiene_plan_versions_plan_id", "fp_hygiene_plan_versions", ["plan_id"])
    op.create_table(
        "fp_hygiene_plan_checks",
        *base(),
        sa.Column("plan_version_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("record_id", pg.UUID(as_uuid=True), nullable=False),
        sa.UniqueConstraint("record_id", name="uq_fp_hygiene_check_record"),
        sa.ForeignKeyConstraint(
            ["venue_id", "plan_version_id"],
            ["fp_hygiene_plan_versions.venue_id", "fp_hygiene_plan_versions.id"],
            name="fk_fp_hygiene_check_plan",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id", "record_id"],
            ["fp_haccp_records.venue_id", "fp_haccp_records.id"],
            name="fk_fp_hygiene_check_record",
        ),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_hygiene_check_request"),
    )
    for name in ("fp_hygiene_plan_versions", "fp_hygiene_plan_checks"):
        op.create_index(f"ix_{name}_venue_id", name, ["venue_id"])
        op.execute(
            f"CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION fp_reject_stock_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {name}_no_truncate BEFORE TRUNCATE ON {name} FOR EACH STATEMENT EXECUTE FUNCTION fp_reject_stock_mutation()"
        )


def downgrade() -> None:
    op.drop_table("fp_hygiene_plan_checks")
    op.drop_table("fp_hygiene_plan_versions")
    op.drop_constraint("uq_fp_haccp_record_scope", "fp_haccp_records", type_="unique")
