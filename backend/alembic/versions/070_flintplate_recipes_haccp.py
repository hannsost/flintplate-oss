"""Versioned recipes, traceable production and immutable HACCP observations."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "070"
down_revision = "069"
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
    op.create_table(
        "fp_recipe_versions",
        *base(),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("menu_item_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_menu_items.id")),
        sa.Column("menu_version", sa.Integer()),
        sa.Column(
            "output_item_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("fp_stock_items.id"),
            nullable=False,
        ),
        sa.Column("yield_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("components", pg.JSONB(), nullable=False),
        sa.Column("cost_cents", sa.Integer(), nullable=False),
        sa.Column("allergens", pg.JSONB(), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_recipe_request"),
    )
    op.create_table(
        "fp_prep_runs",
        *base(),
        sa.Column(
            "recipe_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("fp_recipe_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "operation_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("fp_stock_operations.id"),
            nullable=False,
        ),
        sa.Column(
            "output_lot_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("fp_stock_lots.id"),
            nullable=False,
        ),
        sa.Column("batches", sa.Numeric(18, 6), nullable=False),
        sa.Column("output_quantity", sa.Numeric(18, 6), nullable=False),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_prep_request"),
    )
    op.create_table(
        "fp_haccp_records",
        *base(),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("location", sa.String(120), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Numeric(12, 3), nullable=False),
        sa.Column("minimum", sa.Numeric(12, 3), nullable=False),
        sa.Column("maximum", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("result", sa.String(12), nullable=False),
        sa.Column("correction", sa.String(500), nullable=False),
        sa.Column("corrects_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_haccp_records.id")),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_haccp_request"),
    )
    for name in ("fp_recipe_versions", "fp_prep_runs", "fp_haccp_records"):
        op.create_index(f"ix_{name}_venue_id", name, ["venue_id"])
        op.execute(
            f"CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION fp_reject_stock_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {name}_no_truncate BEFORE TRUNCATE ON {name} FOR EACH STATEMENT EXECUTE FUNCTION fp_reject_stock_mutation()"
        )


def downgrade() -> None:
    for name in ("fp_haccp_records", "fp_prep_runs", "fp_recipe_versions"):
        op.drop_table(name)
