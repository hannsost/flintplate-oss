"""085 cash guards; no application imports or runtime DDL."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op


def upgrade_money_guards() -> None:
    op.create_table(
        "fp_cancellation_checkout_acks",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("order_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_orders.id"), nullable=False),
        sa.Column(
            "execution_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("fp_cancellation_executions.id"),
            nullable=False,
        ),
        sa.Column(
            "device_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_devices.id"), nullable=False
        ),
        sa.Column("request_key", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("reference", sa.String(160), nullable=False),
        sa.Column("order_version", sa.Integer(), nullable=False),
        sa.Column("cancellation_version", sa.Integer(), nullable=False),
        sa.Column("remaining_cents", sa.Integer(), nullable=False),
        sa.Column("cancelled_cents", sa.Integer(), nullable=False),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_cancellation_checkout_key"),
        sa.UniqueConstraint("execution_id", name="uq_fp_cancellation_checkout_execution"),
    )
    for field in ("venue_id", "order_id"):
        op.create_index(
            f"ix_fp_cancellation_checkout_acks_{field}", "fp_cancellation_checkout_acks", [field]
        )
    install_money_guards()


def install_money_guards() -> None:
    """Also callable against metadata-created test schemas with 072 guards installed."""
    # Preserve Python's existing UUID5 receipt identities without rewriting old
    # snapshots or introducing a custom hash implementation. This database-wide
    # dependency deliberately survives a downgrade and disposable test schemas.
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public')
    op.execute("""
      DO $$ BEGIN
        IF NOT EXISTS (
          SELECT 1 FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
          WHERE e.extname='uuid-ossp' AND n.nspname='public'
        ) OR to_regprocedure('public.uuid_generate_v5(uuid,text)') IS NULL THEN
          RAISE EXCEPTION 'FlintPlate 085 requires uuid-ossp and uuid_generate_v5 in public; reconcile the extension schema before migrating';
        END IF;
      END $$
    """)
    op.execute("""
      CREATE FUNCTION fp_cash_line_id(target uuid, line_index bigint, original jsonb)
      RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
        SELECT coalesce(nullif(original->>'line_id',''),
          public.uuid_generate_v5(target,'line'||chr(58)||line_index::text)::text)
      $$
    """)
    op.execute("""
      CREATE FUNCTION fp_cancellation_checkout_pending(target uuid) RETURNS boolean
      LANGUAGE sql STABLE AS $$
        SELECT EXISTS (SELECT 1 FROM fp_cancellation_executions e
          WHERE e.order_id=target AND e.checkout_reconciliation_required
          AND NOT EXISTS (SELECT 1 FROM fp_cancellation_checkout_acks a
                          WHERE a.execution_id=e.id AND a.order_id=e.order_id AND a.venue_id=e.venue_id))
      $$
    """)
    op.execute("""
      CREATE FUNCTION fp_guard_cancellation_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF OLD.paid_at IS NULL AND NEW.paid_at IS NOT NULL AND EXISTS
          (SELECT 1 FROM fp_cancellation_units WHERE order_id=OLD.id) AND NOT EXISTS (
            SELECT 1 FROM fp_cash_entries e,LATERAL jsonb_array_elements(e.allocations) a
            WHERE e.order_id=OLD.id AND e.kind='sale' AND e.amount_cents>0
              AND coalesce(e.external_reference,'cash-ledger:'||e.id::text)=NEW.payment_reference
              AND (a->>'cancellation_version')::int=(SELECT max(result_version) FROM fp_cancellation_executions WHERE order_id=OLD.id)
          ) THEN RAISE EXCEPTION 'Cancellation paid timestamp needs a new positive current sale ledger proof'; END IF;
        IF EXISTS (SELECT 1 FROM fp_cancellation_units WHERE order_id=OLD.id) AND
          ROW((SELECT jsonb_agg(l-'preparation_status' ORDER BY ordinal) FROM jsonb_array_elements(NEW.lines) WITH ORDINALITY AS x(l,ordinal)),NEW.total_cents,NEW.subtotal_cents,NEW.discount_cents,NEW.discount_reason,
              NEW.voucher_cents,NEW.tip_cents,NEW.currency,NEW.venue_id,NEW.actor_id,NEW.device_id,
              NEW.customer_id,NEW.table_id,NEW.tip_recipient_id)
          IS DISTINCT FROM
          ROW((SELECT jsonb_agg(l-'preparation_status' ORDER BY ordinal) FROM jsonb_array_elements(OLD.lines) WITH ORDINALITY AS x(l,ordinal)),OLD.total_cents,OLD.subtotal_cents,OLD.discount_cents,OLD.discount_reason,
              OLD.voucher_cents,OLD.tip_cents,OLD.currency,OLD.venue_id,OLD.actor_id,OLD.device_id,
              OLD.customer_id,OLD.table_id,OLD.tip_recipient_id)
        THEN RAISE EXCEPTION 'Immutable cancellation money snapshot'; END IF;
        RETURN NEW;
      END $$
    """)
    op.execute(
        "CREATE TRIGGER fp_orders_cancellation_snapshot BEFORE UPDATE ON fp_orders FOR EACH ROW EXECUTE FUNCTION fp_guard_cancellation_snapshot()"
    )
    op.execute("""
      CREATE FUNCTION fp_validate_cancellation_cash() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE bill fp_orders; item jsonb; allocation_row jsonb; source_a jsonb; claim jsonb;
        cu fp_cancellation_units; gross bigint; tax bigint; qty bigint;
        paid bigint; paid_tax bigint; credit bigint; cash_total bigint; latest integer;
      BEGIN
        IF NEW.order_id IS NULL THEN RETURN NEW; END IF;
        SELECT * INTO bill FROM fp_orders WHERE id=NEW.order_id FOR NO KEY UPDATE;
        SELECT coalesce(sum(unpaid_credit_cents),0) INTO credit FROM fp_cancellation_units WHERE order_id=NEW.order_id;
        SELECT coalesce(sum(amount_cents),0) INTO cash_total FROM fp_cash_entries WHERE order_id=NEW.order_id AND kind='sale';
        SELECT max(result_version) INTO latest FROM fp_cancellation_executions WHERE order_id=NEW.order_id;
        IF latest IS NOT NULL AND NEW.kind='sale' AND NEW.amount_cents<=0 THEN
          RAISE EXCEPTION 'Cancellation ledger cannot settle by zero payment';
        END IF;
        IF NEW.kind='sale' AND cash_total+NEW.amount_cents > bill.total_cents+bill.tip_cents-credit THEN
          RAISE EXCEPTION 'Cancellation ledger overpayment';
        END IF;
        IF (NEW.kind='refund' OR NEW.method!='voucher') AND fp_cancellation_checkout_pending(NEW.order_id) THEN
          RAISE EXCEPTION 'Cancellation checkout reconciliation required';
        END IF;
        IF jsonb_typeof(NEW.allocations) IS DISTINCT FROM 'array' OR
          (SELECT count(*) FROM jsonb_array_elements(NEW.allocations)) !=
          (SELECT count(DISTINCT (a->>'line_id',a->>'unit')) FROM jsonb_array_elements(NEW.allocations) a)
        THEN RAISE EXCEPTION 'Cancellation duplicate allocation units'; END IF;
        IF NEW.kind='refund' AND NEW.method IN ('cash','voucher') AND NOT EXISTS (
          SELECT 1 FROM fp_memberships WHERE venue_id=NEW.venue_id AND user_id=NEW.actor_id AND role='manager' AND active
        ) THEN RAISE EXCEPTION 'Cancellation refund needs manager confirmation'; END IF;
        IF NEW.method='external' AND NOT EXISTS (
          SELECT 1 FROM fp_devices WHERE id=NEW.device_id AND venue_id=NEW.venue_id
            AND kind='pos' AND active AND expires_at>now() AND scopes @> '["payments:write"]'::jsonb
        ) THEN RAISE EXCEPTION 'Cancellation external payment needs active scoped adapter'; END IF;
        FOR allocation_row IN SELECT * FROM jsonb_array_elements(NEW.allocations) LOOP
          IF jsonb_typeof(allocation_row) IS DISTINCT FROM 'object' OR
             NOT (allocation_row ?& ARRAY['line_id','unit','name','kind','amount_cents','tax_cents']) OR
             allocation_row->>'line_id' IS NULL OR allocation_row->>'unit' IS NULL OR allocation_row->>'name' IS NULL OR allocation_row->>'kind' IS NULL OR
             allocation_row->>'amount_cents' IS NULL OR allocation_row->>'tax_cents' IS NULL OR
             (allocation_row->>'amount_cents')::bigint<=0 OR (allocation_row->>'tax_cents')::bigint<0 OR
             (allocation_row->>'tax_cents')::bigint>(allocation_row->>'amount_cents')::bigint OR (allocation_row->>'unit')::int<0
          THEN RAISE EXCEPTION 'Cancellation invalid allocation cents'; END IF;
          IF NEW.method='external' AND latest IS NOT NULL AND
             (allocation_row->>'cancellation_version')::integer IS DISTINCT FROM latest
          THEN RAISE EXCEPTION 'Cancellation adapter version is stale'; END IF;
          IF NEW.kind='sale' THEN
            IF allocation_row->>'line_id'='tip' THEN
              gross=bill.tip_cents; tax=0; qty=1;
              IF allocation_row->>'kind'!='tip' OR (allocation_row->>'unit')::int!=0 THEN RAISE EXCEPTION 'Cancellation tip allocation mismatch'; END IF;
            ELSE
              SELECT l INTO item FROM jsonb_array_elements(bill.lines) WITH ORDINALITY AS lines(l,line_position)
                WHERE fp_cash_line_id(bill.id,line_position-1,l)=allocation_row->>'line_id';
              IF item IS NULL OR coalesce(item->>'kind','product') IS DISTINCT FROM allocation_row->>'kind' OR item->>'name' IS DISTINCT FROM allocation_row->>'name'
              THEN RAISE EXCEPTION 'Cancellation sale line scope mismatch'; END IF;
              qty=(item->>'quantity')::bigint;
              IF (allocation_row->>'unit')::bigint>=qty THEN RAISE EXCEPTION 'Cancellation sale unit missing'; END IF;
              gross=(item->>'total_cents')::bigint*((allocation_row->>'unit')::bigint+1)/qty-(item->>'total_cents')::bigint*(allocation_row->>'unit')::bigint/qty;
              tax=(item->>'tax_cents')::bigint*((allocation_row->>'unit')::bigint+1)/qty-(item->>'tax_cents')::bigint*(allocation_row->>'unit')::bigint/qty;
            END IF;
            IF EXISTS (SELECT 1 FROM fp_cancellation_units u WHERE u.order_id=NEW.order_id
              AND CASE WHEN u.kind='tip' THEN 'tip' ELSE u.line_id::text END=allocation_row->>'line_id' AND u.unit=(allocation_row->>'unit')::int)
              AND NOT (NEW.method='voucher' AND EXISTS (SELECT 1 FROM fp_cancellation_units u,
                LATERAL jsonb_array_elements(u.refund_allocations) r WHERE u.order_id=NEW.order_id
                AND r->>'original_id'=NEW.id::text AND r->>'method'='voucher'))
            THEN RAISE EXCEPTION 'Cancellation cannot charge cancelled unit'; END IF;
            SELECT coalesce(sum((x->>'amount_cents')::bigint),0) INTO paid
              FROM fp_cash_entries e,LATERAL jsonb_array_elements(e.allocations) x
              WHERE e.order_id=NEW.order_id AND e.kind='sale' AND x->>'line_id'=allocation_row->>'line_id' AND x->>'unit'=allocation_row->>'unit';
            IF gross<=0 OR paid+(allocation_row->>'amount_cents')::bigint>gross OR
              (allocation_row->>'tax_cents')::bigint != tax*(paid+(allocation_row->>'amount_cents')::bigint)/greatest(gross,1)-tax*paid/greatest(gross,1)
            THEN RAISE EXCEPTION 'Cancellation sale unit cents or tax mismatch'; END IF;
          ELSIF NEW.kind='refund' THEN
            SELECT * INTO cu FROM fp_cancellation_units u WHERE u.order_id=NEW.order_id AND u.venue_id=NEW.venue_id
              AND u.execution_id=(allocation_row->>'cancellation_id')::uuid AND u.unit=(allocation_row->>'unit')::int
              AND CASE WHEN u.kind='tip' THEN 'tip' ELSE u.line_id::text END=allocation_row->>'line_id';
            IF cu.id IS NULL THEN RAISE EXCEPTION 'Cancellation approved unit required for refund'; END IF;
            SELECT x INTO claim FROM jsonb_array_elements(cu.refund_allocations) x WHERE x->>'original_id'=NEW.original_id::text;
            SELECT x INTO source_a FROM fp_cash_entries e,LATERAL jsonb_array_elements(e.allocations) x
              WHERE e.id=NEW.original_id AND x->>'line_id'=allocation_row->>'line_id' AND x->>'unit'=allocation_row->>'unit';
            IF claim IS NULL OR source_a IS NULL OR claim->>'method' IS DISTINCT FROM NEW.method OR
              source_a->>'kind' IS DISTINCT FROM allocation_row->>'kind' OR source_a->>'name' IS DISTINCT FROM allocation_row->>'name'
            THEN RAISE EXCEPTION 'Cancellation refund source allocation mismatch'; END IF;
            SELECT coalesce(sum((x->>'amount_cents')::bigint),0) INTO paid
              FROM fp_cash_entries e,LATERAL jsonb_array_elements(e.allocations) x
              WHERE e.original_id=NEW.original_id AND e.kind='refund' AND x->>'line_id'=allocation_row->>'line_id'
                AND x->>'unit'=allocation_row->>'unit' AND x->>'cancellation_id'=allocation_row->>'cancellation_id';
            gross=(claim->>'amount_cents')::bigint; tax=(claim->>'tax_cents')::bigint;
            IF gross<=0 OR paid+(allocation_row->>'amount_cents')::bigint>gross OR
              (allocation_row->>'tax_cents')::bigint!=tax*(paid+(allocation_row->>'amount_cents')::bigint)/greatest(gross,1)-tax*paid/greatest(gross,1)
            THEN RAISE EXCEPTION 'Cancellation refund exceeds unit claim or tax'; END IF;
            IF cu.kind='tip' AND bill.tip_run_id IS NOT NULL THEN
              RAISE EXCEPTION 'Cancellation tip already distributed';
            END IF;
          END IF;
        END LOOP;
        RETURN NEW;
      END $$
    """)
    op.execute(
        "CREATE TRIGGER fp_cash_cancellation_validate BEFORE INSERT ON fp_cash_entries FOR EACH ROW EXECUTE FUNCTION fp_validate_cancellation_cash()"
    )
    op.execute("""
      CREATE FUNCTION fp_validate_cancellation_money() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE target uuid; u fp_cancellation_units; bill fp_orders; item jsonb; claim jsonb;
        original fp_cash_entries; source_a jsonb; qty bigint; gross bigint; tax bigint;
        paid bigint; paid_tax bigint; returned bigint; returned_tax bigint; claims bigint; claims_tax bigint;
      BEGIN
        target=NEW.order_id;
        IF target IS NULL THEN RETURN NEW; END IF;
        SELECT * INTO bill FROM fp_orders WHERE id=target FOR NO KEY UPDATE;
        FOR u IN SELECT * FROM fp_cancellation_units WHERE order_id=target LOOP
          IF u.kind='tip' THEN gross=bill.tip_cents; tax=0; qty=1;
          ELSE
            SELECT l INTO item FROM jsonb_array_elements(bill.lines) WITH ORDINALITY AS lines(l,line_position)
              WHERE fp_cash_line_id(bill.id,line_position-1,l)=u.line_id::text;
            IF item IS NULL OR item->>'name' IS DISTINCT FROM u.name OR coalesce(item->>'kind','product') IS DISTINCT FROM u.kind
            THEN RAISE EXCEPTION 'Cancellation original line snapshot mismatch'; END IF;
            qty=(item->>'quantity')::bigint;
            gross=(item->>'total_cents')::bigint*(u.unit+1)/qty-(item->>'total_cents')::bigint*u.unit/qty;
            tax=(item->>'tax_cents')::bigint*(u.unit+1)/qty-(item->>'tax_cents')::bigint*u.unit/qty;
          END IF;
          IF u.unit<0 OR u.unit>=qty OR u.gross_cents!=gross OR u.tax_cents!=tax OR
             u.venue_id!=bill.venue_id
          THEN RAISE EXCEPTION 'Cancellation original unit snapshot mismatch'; END IF;
          IF u.kind='tip' AND bill.tip_run_id IS NOT NULL THEN RAISE EXCEPTION 'Cancellation distributed tip cannot be changed'; END IF;
          SELECT coalesce(sum((a->>'amount_cents')::bigint),0),coalesce(sum((a->>'tax_cents')::bigint),0)
            INTO paid,paid_tax FROM fp_cash_entries e,LATERAL jsonb_array_elements(e.allocations) a
            WHERE e.order_id=target AND e.kind='sale' AND a->>'line_id'=CASE WHEN u.kind='tip' THEN 'tip' ELSE u.line_id::text END AND (a->>'unit')::int=u.unit;
          SELECT coalesce(sum((a->>'amount_cents')::bigint),0),coalesce(sum((a->>'tax_cents')::bigint),0)
            INTO returned,returned_tax FROM fp_cash_entries e,LATERAL jsonb_array_elements(e.allocations) a
            WHERE e.order_id=target AND e.kind='refund' AND a->>'line_id'=CASE WHEN u.kind='tip' THEN 'tip' ELSE u.line_id::text END
              AND (a->>'unit')::int=u.unit AND a->>'cancellation_id' IS DISTINCT FROM u.execution_id::text;
          IF u.unpaid_credit_cents!=gross-paid OR u.unpaid_tax_cents!=tax-paid_tax OR
            u.already_refunded_cents!=returned OR u.already_refunded_tax_cents!=returned_tax OR
            u.refund_due_cents!=paid-returned OR u.refund_tax_cents!=paid_tax-returned_tax
          THEN RAISE EXCEPTION 'Cancellation money projection not proven by original ledger'; END IF;
          SELECT coalesce(sum((a->>'amount_cents')::bigint),0),coalesce(sum((a->>'tax_cents')::bigint),0)
            INTO claims,claims_tax FROM jsonb_array_elements(u.refund_allocations) a;
          IF claims!=u.refund_due_cents OR claims_tax!=u.refund_tax_cents OR
            (SELECT count(*) FROM jsonb_array_elements(u.refund_allocations)) !=
            (SELECT count(DISTINCT a->>'original_id') FROM jsonb_array_elements(u.refund_allocations) a)
          THEN RAISE EXCEPTION 'Cancellation source claims mismatch'; END IF;
          FOR claim IN SELECT * FROM jsonb_array_elements(u.refund_allocations) LOOP
            SELECT * INTO original FROM fp_cash_entries WHERE id=(claim->>'original_id')::uuid;
            SELECT a INTO source_a FROM jsonb_array_elements(original.allocations) a
              WHERE a->>'line_id'=CASE WHEN u.kind='tip' THEN 'tip' ELSE u.line_id::text END AND (a->>'unit')::int=u.unit;
            SELECT coalesce(sum((a->>'amount_cents')::bigint),0),coalesce(sum((a->>'tax_cents')::bigint),0)
              INTO returned,returned_tax FROM fp_cash_entries e,LATERAL jsonb_array_elements(e.allocations) a
              WHERE e.original_id=original.id AND e.kind='refund' AND a->>'line_id'=source_a->>'line_id'
                AND a->>'unit'=source_a->>'unit' AND a->>'cancellation_id' IS DISTINCT FROM u.execution_id::text;
            IF original.venue_id IS DISTINCT FROM u.venue_id OR original.order_id IS DISTINCT FROM u.order_id OR
              original.kind IS DISTINCT FROM 'sale' OR original.method IS DISTINCT FROM claim->>'method' OR source_a IS NULL OR
              (claim->>'amount_cents')::bigint IS DISTINCT FROM (source_a->>'amount_cents')::bigint-returned OR
              (claim->>'tax_cents')::bigint IS DISTINCT FROM (source_a->>'tax_cents')::bigint-returned_tax
            THEN RAISE EXCEPTION 'Cancellation refund claim not proven by original unit'; END IF;
          END LOOP;
        END LOOP;
        RETURN NEW;
      END $$
    """)
    for table in ("fp_cancellation_units", "fp_cash_entries"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER {table}_cancellation_money AFTER INSERT ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fp_validate_cancellation_money()"
        )
    op.execute("""
      CREATE FUNCTION fp_validate_cancellation_checkout_ack() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE e fp_cancellation_executions; bill fp_orders; latest integer; credit bigint; cancelled bigint; paid bigint;
      BEGIN
        SELECT * INTO e FROM fp_cancellation_executions WHERE id=NEW.execution_id;
        SELECT * INTO bill FROM fp_orders WHERE id=NEW.order_id FOR NO KEY UPDATE;
        SELECT max(result_version) INTO latest FROM fp_cancellation_executions WHERE order_id=NEW.order_id;
        SELECT coalesce(sum(unpaid_credit_cents),0),coalesce(sum(gross_cents),0) INTO credit,cancelled FROM fp_cancellation_units WHERE order_id=NEW.order_id;
        SELECT coalesce(sum(amount_cents),0) INTO paid FROM fp_cash_entries WHERE order_id=NEW.order_id AND kind='sale';
        IF e.order_id IS DISTINCT FROM NEW.order_id OR e.venue_id IS DISTINCT FROM NEW.venue_id OR
          bill.venue_id IS DISTINCT FROM NEW.venue_id OR latest IS DISTINCT FROM NEW.cancellation_version OR
          bill.version IS DISTINCT FROM NEW.order_version OR NEW.remaining_cents!=bill.total_cents+bill.tip_cents-credit-paid OR
          NEW.cancelled_cents!=cancelled OR length(trim(NEW.reference))<1 OR NOT EXISTS (
            SELECT 1 FROM fp_devices WHERE id=NEW.device_id AND venue_id=NEW.venue_id AND kind='pos'
              AND active AND expires_at>now() AND scopes @> '["payments:write"]'::jsonb)
        THEN RAISE EXCEPTION 'Cancellation checkout acknowledgement scope or version mismatch'; END IF;
        RETURN NEW;
      END $$
    """)
    op.execute(
        "CREATE TRIGGER fp_cancellation_checkout_validate BEFORE INSERT ON fp_cancellation_checkout_acks FOR EACH ROW EXECUTE FUNCTION fp_validate_cancellation_checkout_ack()"
    )
    op.execute(
        "CREATE TRIGGER fp_cancellation_checkout_immutable BEFORE UPDATE OR DELETE ON fp_cancellation_checkout_acks FOR EACH ROW EXECUTE FUNCTION fp_reject_cash_mutation()"
    )
    op.execute(
        "CREATE TRIGGER fp_cancellation_checkout_no_truncate BEFORE TRUNCATE ON fp_cancellation_checkout_acks FOR EACH STATEMENT EXECUTE FUNCTION fp_reject_cash_mutation()"
    )
    op.execute("DROP TRIGGER fp_orders_ledger_guard ON fp_orders")
    op.execute("DROP TRIGGER fp_cash_entries_order_guard ON fp_cash_entries")
    op.execute(
        "ALTER FUNCTION fp_validate_order_ledger() RENAME TO fp_validate_order_ledger_pre085"
    )
    op.execute("""
      CREATE FUNCTION fp_validate_order_ledger() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE bill fp_orders; target uuid; received bigint; voucher_paid bigint; sales bigint;
        refunded bigint; refunded_tip bigint; credit bigint; cancelled bigint; cancelled_count bigint;
        claimed bigint; returned_claims bigint; remaining bigint; expected text; original_units bigint;
      BEGIN
        IF TG_TABLE_NAME='fp_orders' THEN target=NEW.id; ELSE target=NEW.order_id; END IF;
        IF target IS NULL THEN RETURN NEW; END IF;
        SELECT * INTO bill FROM fp_orders WHERE id=target;
        SELECT coalesce(sum(amount_cents),0),coalesce(sum(amount_cents) FILTER(WHERE method='voucher'),0),count(*)
          INTO received,voucher_paid,sales FROM fp_cash_entries WHERE order_id=target AND kind='sale';
        SELECT coalesce(sum(unpaid_credit_cents),0),coalesce(sum(gross_cents),0),coalesce(sum(refund_due_cents),0),count(*)
          INTO credit,cancelled,claimed,cancelled_count FROM fp_cancellation_units WHERE order_id=target;
        SELECT coalesce(sum((l->>'quantity')::bigint),0)+CASE WHEN bill.tip_cents>0 THEN 1 ELSE 0 END
          INTO original_units FROM jsonb_array_elements(bill.lines) l;
        -- A combined SQL boolean expression does not protect a trigger record
        -- from field resolution on another table (or an INSERT without OLD).
        IF TG_TABLE_NAME='fp_orders' THEN
          IF TG_OP='UPDATE' THEN
            IF sales=0 AND cancelled_count=0 AND OLD.paid_at IS NOT NULL
              AND bill.paid_at=OLD.paid_at AND bill.tip_refunded_cents=OLD.tip_refunded_cents
              AND bill.payment_status IS NOT DISTINCT FROM OLD.payment_status AND bill.status IS NOT DISTINCT FROM OLD.status
              AND ROW(bill.lines,bill.total_cents,bill.subtotal_cents,bill.discount_cents,bill.voucher_cents,bill.tip_cents,bill.currency)
                 IS NOT DISTINCT FROM ROW(OLD.lines,OLD.total_cents,OLD.subtotal_cents,OLD.discount_cents,OLD.voucher_cents,OLD.tip_cents,OLD.currency)
            THEN RETURN NEW; END IF;
          END IF;
        END IF;
        SELECT coalesce(-sum(amount_cents),0) INTO refunded FROM fp_cash_entries WHERE order_id=target AND kind='refund';
        SELECT coalesce(sum((a->>'amount_cents')::bigint) FILTER(WHERE a->>'kind'='tip'),0),
               coalesce(sum((a->>'amount_cents')::bigint) FILTER(WHERE a ? 'cancellation_id'),0)
          INTO refunded_tip,returned_claims FROM fp_cash_entries e,LATERAL jsonb_array_elements(e.allocations) a
          WHERE e.order_id=target AND e.kind='refund';
        IF bill.tip_refunded_cents!=refunded_tip THEN RAISE EXCEPTION 'Cash ledger does not prove refunded tip'; END IF;
        remaining=bill.total_cents+bill.tip_cents-credit-received;
        IF remaining<0 OR (sales>0 AND voucher_paid!=bill.voucher_cents) OR
          (bill.paid_at IS NOT NULL AND (sales=0 OR remaining!=0)) OR (bill.status='settled' AND remaining!=0)
        THEN RAISE EXCEPTION 'Cash ledger does not prove corrected settlement'; END IF;
        IF cancelled_count>0 THEN
          IF remaining>0 THEN expected=CASE WHEN sales>0 THEN 'partial' WHEN bill.pos_requested THEN 'requested' ELSE 'open' END;
          ELSIF claimed>returned_claims THEN expected='refund_pending';
          ELSIF cancelled_count=original_units THEN expected=CASE WHEN refunded>0 THEN 'refunded' ELSE 'cancelled' END;
          ELSE expected=CASE WHEN bill.paid_at IS NOT NULL THEN 'paid' ELSE 'adjusted' END;
          END IF;
          IF bill.payment_status IS DISTINCT FROM expected THEN RAISE EXCEPTION 'Cancellation cash ledger payment projection mismatch'; END IF;
        ELSE
          IF bill.paid_at IS NOT NULL OR bill.payment_status='paid' OR bill.status='settled' THEN
            IF sales=0 OR remaining!=0 OR voucher_paid!=bill.voucher_cents THEN RAISE EXCEPTION 'Cash ledger does not prove full settlement'; END IF;
          ELSIF sales>0 THEN
            IF remaining<=0 OR bill.payment_status!='partial' THEN RAISE EXCEPTION 'Cash ledger partial payment mismatch'; END IF;
          ELSIF bill.payment_status='partial' THEN RAISE EXCEPTION 'Cash ledger does not prove partial payment'; END IF;
          IF refunded>0 AND (bill.paid_at IS NULL OR
            (refunded=received AND bill.payment_status!='refunded') OR (refunded<received AND bill.payment_status!='partially_refunded'))
          THEN RAISE EXCEPTION 'Cash ledger refund projection mismatch'; END IF;
          IF refunded=0 AND bill.payment_status IN ('refunded','partially_refunded','refund_pending','adjusted')
          THEN RAISE EXCEPTION 'Cash ledger does not prove correction'; END IF;
        END IF;
        RETURN NEW;
      END $$
    """)
    for table in ("fp_orders", "fp_cash_entries", "fp_cancellation_units"):
        name = (
            "fp_orders_ledger_guard"
            if table == "fp_orders"
            else (
                "fp_cash_entries_order_guard"
                if table == "fp_cash_entries"
                else "fp_cancellation_units_order_guard"
            )
        )
        action = "INSERT OR UPDATE" if table == "fp_orders" else "INSERT"
        op.execute(
            f"CREATE CONSTRAINT TRIGGER {name} AFTER {action} ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fp_validate_order_ledger()"
        )


def downgrade_money_guards() -> None:
    for table, trigger in (
        ("fp_orders", "fp_orders_ledger_guard"),
        ("fp_cash_entries", "fp_cash_entries_order_guard"),
        ("fp_cancellation_units", "fp_cancellation_units_order_guard"),
        ("fp_cancellation_units", "fp_cancellation_units_cancellation_money"),
        ("fp_cash_entries", "fp_cash_entries_cancellation_money"),
    ):
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
    op.execute("DROP FUNCTION fp_validate_order_ledger()")
    op.execute(
        "ALTER FUNCTION fp_validate_order_ledger_pre085() RENAME TO fp_validate_order_ledger"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER fp_orders_ledger_guard AFTER INSERT OR UPDATE ON fp_orders DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fp_validate_order_ledger()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER fp_cash_entries_order_guard AFTER INSERT ON fp_cash_entries DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fp_validate_order_ledger()"
    )
    op.execute("DROP TRIGGER fp_cash_cancellation_validate ON fp_cash_entries")
    op.execute("DROP TRIGGER fp_orders_cancellation_snapshot ON fp_orders")
    op.execute("DROP FUNCTION fp_validate_cancellation_cash()")
    op.execute("DROP FUNCTION fp_validate_cancellation_money()")
    op.execute("DROP FUNCTION fp_guard_cancellation_snapshot()")
    op.execute("DROP FUNCTION fp_cash_line_id(uuid,bigint,jsonb)")
    op.drop_table("fp_cancellation_checkout_acks")
    op.execute("DROP FUNCTION fp_validate_cancellation_checkout_ack()")
    op.execute("DROP FUNCTION fp_cancellation_checkout_pending(uuid)")
