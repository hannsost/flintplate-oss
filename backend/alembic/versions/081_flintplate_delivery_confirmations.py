"""Record versioned supplier delivery confirmations and attributed arrivals."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "081"
down_revision = "080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fp_delivery_confirmations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("request_key", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("line_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("previous_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("expected_on", sa.Date(), nullable=False),
        sa.Column("paid_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("bonus_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_delivery_scope"),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_delivery_request"),
        sa.UniqueConstraint("line_id", "version", name="uq_fp_delivery_version"),
        sa.CheckConstraint(
            "version > 0 AND paid_quantity >= 0 AND bonus_quantity >= 0",
            name="ck_fp_delivery_quantity",
        ),
        sa.CheckConstraint(
            "(status = 'confirmed' AND paid_quantity + bonus_quantity > 0) OR (status = 'cancelled' AND paid_quantity + bonus_quantity = 0)",
            name="ck_fp_delivery_status",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id", "line_id"],
            ["fp_purchase_order_lines.venue_id", "fp_purchase_order_lines.id"],
            name="fk_fp_delivery_line",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id", "previous_id"],
            ["fp_delivery_confirmations.venue_id", "fp_delivery_confirmations.id"],
            name="fk_fp_delivery_previous",
        ),
    )
    op.create_index(
        "ix_fp_delivery_confirmations_venue_id", "fp_delivery_confirmations", ["venue_id"]
    )
    op.create_index(
        "ix_fp_delivery_confirmations_line_id", "fp_delivery_confirmations", ["line_id"]
    )
    op.add_column(
        "fp_purchase_receipts", sa.Column("confirmation_id", pg.UUID(as_uuid=True), nullable=True)
    )
    op.create_index(
        "ix_fp_purchase_receipts_confirmation_id", "fp_purchase_receipts", ["confirmation_id"]
    )
    op.create_foreign_key(
        "fk_fp_purchase_receipt_confirmation",
        "fp_purchase_receipts",
        "fp_delivery_confirmations",
        ["venue_id", "confirmation_id"],
        ["venue_id", "id"],
    )
    op.execute(
        "CREATE TRIGGER fp_delivery_immutable BEFORE UPDATE OR DELETE ON fp_delivery_confirmations FOR EACH ROW EXECUTE FUNCTION fp_reject_purchase_mutation()"
    )
    op.execute(
        "CREATE TRIGGER fp_delivery_no_truncate BEFORE TRUNCATE ON fp_delivery_confirmations FOR EACH STATEMENT EXECUTE FUNCTION fp_reject_purchase_mutation()"
    )
    op.execute("""CREATE FUNCTION fp_guard_delivery_version() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE previous fp_delivery_confirmations;
      BEGIN
        PERFORM 1 FROM fp_venues WHERE id=NEW.venue_id FOR UPDATE;
        SELECT * INTO previous FROM fp_delivery_confirmations WHERE line_id=NEW.line_id ORDER BY version DESC LIMIT 1;
        IF NEW.version <> coalesce(previous.version,0)+1 OR NEW.previous_id IS DISTINCT FROM previous.id THEN
          RAISE EXCEPTION 'FlintPlate delivery confirmation must follow the current version';
        END IF;
        RETURN NEW;
      END $$""")
    op.execute(
        "CREATE TRIGGER fp_delivery_version_guard BEFORE INSERT ON fp_delivery_confirmations FOR EACH ROW EXECUTE FUNCTION fp_guard_delivery_version()"
    )
    op.execute(
        """CREATE FUNCTION fp_guard_receipt_confirmation() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE
        confirmed fp_delivery_confirmations;
        current_id uuid;
        arrived_paid numeric;
        arrived_bonus numeric;
      BEGIN
        IF NEW.confirmation_id IS NULL THEN RETURN NEW; END IF;
        -- Serialize with replacement promises and other arrivals before reading totals.
        PERFORM 1 FROM fp_venues WHERE id=NEW.venue_id FOR UPDATE;
        SELECT * INTO confirmed FROM fp_delivery_confirmations
          WHERE id=NEW.confirmation_id AND venue_id=NEW.venue_id AND line_id=NEW.line_id;
        IF NOT FOUND THEN
          RAISE EXCEPTION 'FlintPlate receipt confirmation belongs to another purchase line';
        END IF;
        SELECT id INTO current_id FROM fp_delivery_confirmations
          WHERE venue_id=NEW.venue_id AND line_id=NEW.line_id ORDER BY version DESC LIMIT 1;
        IF confirmed.status <> 'confirmed' OR confirmed.id IS DISTINCT FROM current_id THEN
          RAISE EXCEPTION 'FlintPlate receipt requires the current confirmed delivery revision';
        END IF;
        -- Rejected paid/bonus goods also arrived and must consume the promise.
        SELECT coalesce(sum(accepted_quantity + rejected_quantity
                            - accepted_bonus_quantity - rejected_bonus_quantity), 0),
               coalesce(sum(accepted_bonus_quantity + rejected_bonus_quantity), 0)
          INTO arrived_paid, arrived_bonus FROM fp_purchase_receipts
          WHERE venue_id=NEW.venue_id AND line_id=NEW.line_id
            AND confirmation_id=NEW.confirmation_id;
        IF arrived_paid + NEW.accepted_quantity + NEW.rejected_quantity
            - NEW.accepted_bonus_quantity - NEW.rejected_bonus_quantity > confirmed.paid_quantity
          OR arrived_bonus + NEW.accepted_bonus_quantity + NEW.rejected_bonus_quantity
            > confirmed.bonus_quantity THEN
          RAISE EXCEPTION 'FlintPlate arrived quantities exceed the delivery confirmation';
        END IF;
        RETURN NEW;
      END $$"""
    )
    op.execute(
        "CREATE TRIGGER fp_receipt_confirmation_guard BEFORE INSERT ON fp_purchase_receipts FOR EACH ROW EXECUTE FUNCTION fp_guard_receipt_confirmation()"
    )


def downgrade() -> None:
    op.execute(
        """DO $$ BEGIN IF EXISTS(SELECT 1 FROM fp_delivery_confirmations) THEN
      RAISE EXCEPTION 'FlintPlate delivery evidence prevents destructive downgrade'; END IF; END $$"""
    )
    op.execute("DROP TRIGGER fp_receipt_confirmation_guard ON fp_purchase_receipts")
    op.execute("DROP FUNCTION fp_guard_receipt_confirmation()")
    op.drop_constraint(
        "fk_fp_purchase_receipt_confirmation", "fp_purchase_receipts", type_="foreignkey"
    )
    op.drop_index("ix_fp_purchase_receipts_confirmation_id", table_name="fp_purchase_receipts")
    op.drop_column("fp_purchase_receipts", "confirmation_id")
    op.execute("DROP TRIGGER fp_delivery_version_guard ON fp_delivery_confirmations")
    op.execute("DROP FUNCTION fp_guard_delivery_version()")
    op.drop_table("fp_delivery_confirmations")
