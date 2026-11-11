"""Physical till sessions, immutable tenders and linked refunds."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "072"
down_revision = "071"
branch_labels = None
depends_on = None

FINANCIAL_HISTORY_TABLES = (
    "fp_voucher_entries",
    "fp_loyalty_entries",
    "fp_tip_runs",
    "fp_tip_shares",
)


def base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
    ]


def upgrade() -> None:
    op.add_column(
        "fp_orders",
        sa.Column("tip_refunded_cents", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_fp_tip_refunded",
        "fp_orders",
        "tip_refunded_cents >= 0 AND tip_refunded_cents <= tip_cents",
    )
    op.create_table(
        "fp_cash_registers",
        *base_columns(),
        sa.Column("name", sa.String(80), nullable=False),
        sa.UniqueConstraint("venue_id", "name", name="uq_fp_cash_register_name"),
    )
    op.create_table(
        "fp_cash_sessions",
        *base_columns(),
        sa.Column(
            "register_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("fp_cash_registers.id"),
            nullable=False,
        ),
        sa.Column("operator_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_key", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("counted_cents", sa.Integer(), nullable=True),
        sa.Column("expected_cents", sa.Integer(), nullable=True),
        sa.Column("difference_cents", sa.Integer(), nullable=True),
        sa.Column("count_request_key", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("count_request_hash", sa.String(64), nullable=True),
        sa.Column("count_reason", sa.String(300), nullable=False, server_default=""),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_cash_session_request"),
        sa.CheckConstraint(
            "status IN ('open','counted','closed')", name="ck_fp_cash_session_status"
        ),
    )
    op.create_index(
        "uq_fp_cash_session_active",
        "fp_cash_sessions",
        ["register_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('open','counted')"),
    )
    op.create_table(
        "fp_cash_entries",
        *base_columns(),
        sa.Column(
            "session_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_cash_sessions.id"), nullable=True
        ),
        sa.Column("order_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_orders.id"), nullable=True),
        sa.Column(
            "original_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_cash_entries.id"), nullable=True
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("received_cents", sa.Integer(), nullable=True),
        sa.Column("change_cents", sa.Integer(), nullable=True),
        sa.Column("points_delta", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("allocations", pg.JSONB(), nullable=False, server_default="[]"),
        sa.Column("payer", sa.String(80), nullable=False, server_default=""),
        sa.Column("reason", sa.String(300), nullable=False, server_default=""),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "device_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_devices.id"), nullable=True
        ),
        sa.Column("external_reference", sa.String(160), nullable=True),
        sa.Column("request_key", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_cash_entry_request"),
        sa.UniqueConstraint("venue_id", "external_reference", name="uq_fp_cash_external_reference"),
        sa.CheckConstraint("method IN ('cash','external','voucher')", name="ck_fp_cash_method"),
        sa.CheckConstraint(
            "kind IN ('opening','movement','sale','refund')", name="ck_fp_cash_kind"
        ),
        sa.CheckConstraint(
            "(kind != 'sale' OR amount_cents >= 0) AND (kind != 'refund' OR amount_cents < 0)",
            name="ck_fp_cash_sign",
        ),
    )
    for table, columns in (
        ("fp_cash_registers", ["venue_id"]),
        ("fp_cash_sessions", ["venue_id", "register_id"]),
        ("fp_cash_entries", ["venue_id", "session_id", "order_id", "original_id"]),
    ):
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])
    install_guards()


def install_guards() -> None:
    op.execute("""
      CREATE FUNCTION fp_reject_cash_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'Cash ledger is append-only'; END $$
    """)
    for name in FINANCIAL_HISTORY_TABLES:
        op.execute(
            f"CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE ON {name} "
            "FOR EACH ROW EXECUTE FUNCTION fp_reject_cash_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {name}_no_truncate BEFORE TRUNCATE ON {name} "
            "FOR EACH STATEMENT EXECUTE FUNCTION fp_reject_cash_mutation()"
        )
    op.execute(
        "CREATE TRIGGER fp_cash_entries_immutable BEFORE UPDATE OR DELETE ON fp_cash_entries FOR EACH ROW EXECUTE FUNCTION fp_reject_cash_mutation()"
    )
    op.execute(
        "CREATE TRIGGER fp_cash_entries_no_truncate BEFORE TRUNCATE ON fp_cash_entries FOR EACH STATEMENT EXECUTE FUNCTION fp_reject_cash_mutation()"
    )
    op.execute("""
      CREATE FUNCTION fp_validate_cash_entry() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE bill fp_orders; original fp_cash_entries; allocated bigint; previous bigint;
      BEGIN
        IF NEW.order_id IS NULL THEN
          IF NEW.kind NOT IN ('opening','movement') OR NEW.method != 'cash' THEN
            RAISE EXCEPTION 'Cash ledger movement needs a drawer or order';
          END IF;
        ELSE
          SELECT * INTO bill FROM fp_orders WHERE id=NEW.order_id FOR NO KEY UPDATE;
          IF bill.venue_id IS DISTINCT FROM NEW.venue_id OR bill.currency IS DISTINCT FROM NEW.currency THEN
            RAISE EXCEPTION 'Cash ledger order scope mismatch';
          END IF;
          SELECT coalesce(sum((a->>'amount_cents')::bigint),0) INTO allocated FROM jsonb_array_elements(NEW.allocations) a;
          IF allocated != abs(NEW.amount_cents) THEN RAISE EXCEPTION 'Cash ledger allocations mismatch'; END IF;
          IF NEW.kind='sale' THEN
            SELECT coalesce(sum(amount_cents),0) INTO previous FROM fp_cash_entries WHERE order_id=NEW.order_id AND kind='sale';
            IF previous + NEW.amount_cents > bill.total_cents + bill.tip_cents THEN
              RAISE EXCEPTION 'Cash ledger overpayment';
            END IF;
          ELSIF NEW.kind='refund' THEN
            -- The order lock above serializes all its tenders and refunds.
            -- Immutable ledger rows need no UPDATE privilege or row lock.
            SELECT * INTO original FROM fp_cash_entries WHERE id=NEW.original_id;
            IF original.kind IS DISTINCT FROM 'sale' OR original.order_id IS DISTINCT FROM NEW.order_id OR original.method IS DISTINCT FROM NEW.method THEN
              RAISE EXCEPTION 'Cash ledger refund source mismatch';
            END IF;
            SELECT coalesce(-sum(amount_cents),0) INTO previous FROM fp_cash_entries WHERE original_id=NEW.original_id AND kind='refund';
            IF previous - NEW.amount_cents > original.amount_cents THEN RAISE EXCEPTION 'Cash ledger over-refund'; END IF;
          ELSE RAISE EXCEPTION 'Cash ledger order entry kind mismatch';
          END IF;
        END IF;
        IF NEW.method='cash' AND NOT EXISTS (SELECT 1 FROM fp_cash_sessions WHERE id=NEW.session_id AND venue_id=NEW.venue_id AND status='open') THEN
          RAISE EXCEPTION 'Cash ledger needs an open matching drawer';
        END IF;
        IF NEW.method='external' AND (NEW.device_id IS NULL OR NEW.external_reference IS NULL) THEN
          RAISE EXCEPTION 'Cash ledger external tender needs adapter and reference';
        END IF;
        RETURN NEW;
      END $$
    """)
    op.execute(
        "CREATE TRIGGER fp_cash_entries_validate BEFORE INSERT ON fp_cash_entries FOR EACH ROW EXECUTE FUNCTION fp_validate_cash_entry()"
    )
    op.execute("""
      CREATE FUNCTION fp_guard_order_money() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP='UPDATE' THEN
          IF (OLD.pos_requested OR OLD.paid_at IS NOT NULL) AND (
            (OLD.pos_requested AND NOT NEW.pos_requested) OR NEW.lines IS DISTINCT FROM OLD.lines OR
            NEW.total_cents IS DISTINCT FROM OLD.total_cents OR NEW.subtotal_cents IS DISTINCT FROM OLD.subtotal_cents OR
            NEW.discount_cents IS DISTINCT FROM OLD.discount_cents OR NEW.discount_reason IS DISTINCT FROM OLD.discount_reason OR
            NEW.voucher_cents IS DISTINCT FROM OLD.voucher_cents OR NEW.tip_cents IS DISTINCT FROM OLD.tip_cents OR
            NEW.currency IS DISTINCT FROM OLD.currency OR NEW.venue_id IS DISTINCT FROM OLD.venue_id OR
            NEW.actor_id IS DISTINCT FROM OLD.actor_id OR NEW.device_id IS DISTINCT FROM OLD.device_id OR
            NEW.customer_id IS DISTINCT FROM OLD.customer_id OR NEW.table_id IS DISTINCT FROM OLD.table_id OR
            NEW.tip_recipient_id IS DISTINCT FROM OLD.tip_recipient_id
          ) THEN RAISE EXCEPTION 'Immutable checkout money snapshot'; END IF;
          IF OLD.paid_at IS NOT NULL AND NEW.paid_at IS DISTINCT FROM OLD.paid_at THEN
            RAISE EXCEPTION 'Cash ledger paid timestamp cannot be rewritten';
          END IF;
        END IF;
        IF TG_OP='UPDATE' AND NEW.tip_refunded_cents IS DISTINCT FROM OLD.tip_refunded_cents THEN
          IF NEW.tip_refunded_cents < OLD.tip_refunded_cents OR OLD.tip_run_id IS NOT NULL THEN
            RAISE EXCEPTION 'Cash ledger tip already distributed or refund decreased';
          END IF;
        END IF;
        RETURN NEW;
      END $$
    """)
    op.execute(
        "CREATE TRIGGER fp_orders_money_guard BEFORE INSERT OR UPDATE ON fp_orders FOR EACH ROW EXECUTE FUNCTION fp_guard_order_money()"
    )
    op.execute("""
      CREATE FUNCTION fp_validate_order_ledger() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE bill fp_orders; target uuid; received bigint; voucher_paid bigint; sales bigint; refunded_tip bigint; refunded bigint;
      BEGIN
        IF TG_TABLE_NAME='fp_cash_entries' THEN target=NEW.order_id; ELSE target=NEW.id; END IF;
        IF target IS NULL THEN RETURN NEW; END IF;
        SELECT * INTO bill FROM fp_orders WHERE id=target;
        SELECT coalesce(sum(amount_cents),0),coalesce(sum(amount_cents) FILTER(WHERE method='voucher'),0),count(*)
          INTO received,voucher_paid,sales FROM fp_cash_entries WHERE order_id=target AND kind='sale';
        -- Preserve historical paid records while preventing newly forged settlements.
        IF sales=0 AND TG_TABLE_NAME='fp_orders' AND TG_OP='UPDATE' THEN
          IF OLD.paid_at IS NOT NULL AND bill.paid_at=OLD.paid_at
            AND bill.tip_refunded_cents=OLD.tip_refunded_cents
            AND bill.payment_status IS NOT DISTINCT FROM OLD.payment_status
            AND bill.status IS NOT DISTINCT FROM OLD.status
            AND ROW(bill.lines,bill.total_cents,bill.subtotal_cents,bill.discount_cents,bill.voucher_cents,bill.tip_cents,bill.currency)
                IS NOT DISTINCT FROM ROW(OLD.lines,OLD.total_cents,OLD.subtotal_cents,OLD.discount_cents,OLD.voucher_cents,OLD.tip_cents,OLD.currency)
          THEN RETURN NEW; END IF;
        END IF;
        IF bill.paid_at IS NOT NULL OR bill.payment_status='paid' OR bill.status='settled' THEN
          IF sales=0 OR received != bill.total_cents + bill.tip_cents OR voucher_paid != bill.voucher_cents THEN
            RAISE EXCEPTION 'Cash ledger does not prove full settlement';
          END IF;
        ELSIF sales>0 THEN
          IF received >= bill.total_cents + bill.tip_cents OR bill.payment_status!='partial' THEN
            RAISE EXCEPTION 'Cash ledger and partial payment status differ';
          END IF;
        ELSIF bill.payment_status='partial' THEN
          RAISE EXCEPTION 'Cash ledger does not prove partial settlement';
        END IF;
        SELECT coalesce(-sum(amount_cents),0) INTO refunded FROM fp_cash_entries WHERE order_id=target AND kind='refund';
        SELECT coalesce(sum((a->>'amount_cents')::bigint),0) INTO refunded_tip FROM fp_cash_entries e,
          LATERAL jsonb_array_elements(e.allocations) a WHERE e.order_id=target AND e.kind='refund' AND a->>'kind'='tip';
        IF bill.tip_refunded_cents != refunded_tip THEN RAISE EXCEPTION 'Cash ledger does not prove refunded tip'; END IF;
        IF refunded>0 AND (bill.paid_at IS NULL OR
          (refunded=received AND bill.payment_status!='refunded') OR
          (refunded<received AND bill.payment_status!='partially_refunded')) THEN
          RAISE EXCEPTION 'Cash ledger and refund status differ';
        END IF;
        IF refunded=0 AND bill.payment_status IN ('refunded','partially_refunded') THEN
          RAISE EXCEPTION 'Cash ledger does not prove refund';
        END IF;
        RETURN NEW;
      END $$
    """)
    op.execute(
        "CREATE CONSTRAINT TRIGGER fp_orders_ledger_guard AFTER INSERT OR UPDATE ON fp_orders DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fp_validate_order_ledger()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER fp_cash_entries_order_guard AFTER INSERT ON fp_cash_entries DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fp_validate_order_ledger()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER fp_cash_entries_order_guard ON fp_cash_entries")
    op.execute("DROP TRIGGER fp_orders_ledger_guard ON fp_orders")
    op.execute("DROP FUNCTION fp_validate_order_ledger()")
    op.execute("DROP TRIGGER fp_orders_money_guard ON fp_orders")
    op.execute("DROP FUNCTION fp_guard_order_money()")
    op.execute("DROP TRIGGER fp_cash_entries_validate ON fp_cash_entries")
    op.execute("DROP FUNCTION fp_validate_cash_entry()")
    op.execute("DROP TRIGGER fp_cash_entries_no_truncate ON fp_cash_entries")
    op.execute("DROP TRIGGER fp_cash_entries_immutable ON fp_cash_entries")
    for name in FINANCIAL_HISTORY_TABLES:
        op.execute(f"DROP TRIGGER {name}_no_truncate ON {name}")
        op.execute(f"DROP TRIGGER {name}_immutable ON {name}")
    op.execute("DROP FUNCTION fp_reject_cash_mutation()")
    op.drop_table("fp_cash_entries")
    op.drop_table("fp_cash_sessions")
    op.drop_table("fp_cash_registers")
    op.drop_constraint("ck_fp_tip_refunded", "fp_orders", type_="check")
    op.drop_column("fp_orders", "tip_refunded_cents")
