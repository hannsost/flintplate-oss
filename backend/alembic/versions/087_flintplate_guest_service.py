"""Audited visit contexts and atomic independent guest orders.

Revision ID: 087
Revises: 086
"""

from __future__ import annotations

import re

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "087"
down_revision = "086"
branch_labels = None
depends_on = None

APPEND_ONLY = (
    "fp_service_commands",
    "fp_service_rounds",
    "fp_service_round_children",
    "fp_service_unit_assignments",
)
STATE_TABLES = ("fp_service_settings", "fp_service_visits", "fp_guest_tabs")


def base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("venue_id", sa.Uuid(), sa.ForeignKey("fp_venues.id"), nullable=False),
    ]


def head() -> list[sa.Column]:
    return [
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "last_command_id",
            sa.Uuid(),
            sa.ForeignKey("fp_service_commands.id", deferrable=True, initially="DEFERRED"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "fp_service_commands",
        *base(),
        sa.Column("request_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("snapshots", JSONB(), nullable=False),
        sa.Column("result", JSONB(), nullable=False),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_service_command_key"),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_service_command_scope"),
    )
    op.create_table(
        "fp_service_settings",
        *base(),
        *head(),
        sa.Column("workflow", sa.String(20), nullable=False),
        sa.Column("guest_label_mode", sa.String(24), nullable=False),
        sa.UniqueConstraint("venue_id", name="uq_fp_service_settings_venue"),
        sa.CheckConstraint(
            "version>0 AND workflow IN ('table','guest','counter','mixed') AND guest_label_mode IN ('number','name_or_number','seat_or_number')",
            name="ck_fp_service_settings",
        ),
    )
    op.create_table(
        "fp_service_visits",
        *base(),
        *head(),
        sa.Column(
            "reservation_id",
            sa.Uuid(),
            sa.ForeignKey("fp_reservations.id"),
            nullable=True,
            unique=True,
        ),
        sa.Column("number", sa.String(24), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_service_visit_scope"),
        sa.UniqueConstraint("venue_id", "number", name="uq_fp_service_visit_number"),
        sa.CheckConstraint("version>0", name="ck_fp_service_visit_version"),
    )
    op.create_table(
        "fp_guest_tabs",
        *base(),
        *head(),
        sa.Column("visit_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("current_table_id", sa.Uuid(), sa.ForeignKey("fp_tables.id"), nullable=True),
        sa.Column("seat_label", sa.String(30), nullable=False),
        sa.Column("present", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["venue_id", "visit_id"], ["fp_service_visits.venue_id", "fp_service_visits.id"]
        ),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_guest_tab_scope"),
        sa.UniqueConstraint("visit_id", "kind", "number", name="uq_fp_guest_tab_number"),
        sa.CheckConstraint(
            "version>0 AND number>0 AND kind IN ('guest','shared') AND (kind!='shared' OR present=false)",
            name="ck_fp_guest_tab",
        ),
    )
    op.create_index(
        "uq_fp_guest_tab_shared",
        "fp_guest_tabs",
        ["visit_id"],
        unique=True,
        postgresql_where=sa.text("kind='shared'"),
    )
    op.create_table(
        "fp_service_rounds",
        *base(),
        sa.Column("visit_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column(
            "command_id",
            sa.Uuid(),
            sa.ForeignKey("fp_service_commands.id", deferrable=True, initially="DEFERRED"),
            nullable=False,
            unique=True,
        ),
        sa.Column("expected_tab_ids", JSONB(), nullable=False),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_service_round_scope"),
        sa.UniqueConstraint("visit_id", "number", name="uq_fp_service_round_number"),
        sa.ForeignKeyConstraint(
            ["venue_id", "visit_id"], ["fp_service_visits.venue_id", "fp_service_visits.id"]
        ),
    )
    op.create_table(
        "fp_service_round_children",
        *base(),
        sa.Column("round_id", sa.Uuid(), nullable=False),
        sa.Column("guest_tab_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("label_snapshot", sa.String(160), nullable=False),
        sa.UniqueConstraint("round_id", "guest_tab_id", name="uq_fp_service_round_tab"),
        sa.ForeignKeyConstraint(
            ["venue_id", "round_id"], ["fp_service_rounds.venue_id", "fp_service_rounds.id"]
        ),
        sa.ForeignKeyConstraint(
            ["venue_id", "guest_tab_id"], ["fp_guest_tabs.venue_id", "fp_guest_tabs.id"]
        ),
        sa.ForeignKeyConstraint(["venue_id", "order_id"], ["fp_orders.venue_id", "fp_orders.id"]),
    )
    op.create_table(
        "fp_service_unit_assignments",
        *base(),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("line_id", sa.Uuid(), nullable=False),
        sa.Column("unit", sa.Integer(), nullable=False),
        sa.Column("guest_tab_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "command_id",
            sa.Uuid(),
            sa.ForeignKey("fp_service_commands.id", deferrable=True, initially="DEFERRED"),
            nullable=False,
        ),
        sa.Column("before_tab_id", sa.Uuid(), sa.ForeignKey("fp_guest_tabs.id"), nullable=True),
        sa.Column("cart_row_id", sa.Uuid(), nullable=True),
        sa.Column("cart_unit", sa.Integer(), nullable=True),
        sa.UniqueConstraint(
            "order_id", "line_id", "unit", "version", name="uq_fp_service_assignment_revision"
        ),
        sa.ForeignKeyConstraint(["venue_id", "order_id"], ["fp_orders.venue_id", "fp_orders.id"]),
        sa.ForeignKeyConstraint(
            ["venue_id", "guest_tab_id"], ["fp_guest_tabs.venue_id", "fp_guest_tabs.id"]
        ),
        sa.CheckConstraint(
            "unit>=0 AND version>0 AND ((cart_row_id IS NULL AND cart_unit IS NULL) OR (cart_row_id IS NOT NULL AND cart_unit>=0))",
            name="ck_fp_service_assignment",
        ),
    )
    for table in (*APPEND_ONLY, *STATE_TABLES):
        op.create_index(f"ix_{table}_id", table, ["id"])
    for table in (*APPEND_ONLY, "fp_service_visits", "fp_guest_tabs"):
        op.create_index(f"ix_{table}_venue_id", table, ["venue_id"])
    for table, column in (
        ("fp_guest_tabs", "visit_id"),
        ("fp_service_rounds", "visit_id"),
        ("fp_service_round_children", "round_id"),
        ("fp_service_round_children", "order_id"),
        ("fp_service_unit_assignments", "order_id"),
        ("fp_service_unit_assignments", "command_id"),
    ):
        op.create_index(f"ix_{table}_{column}", table, [column])
    install_guards()


def _execute(sql: str) -> None:
    # asyncpg prepares each statement; function bodies keep their inner semicolons.
    for statement in re.split(r";\s*(?=CREATE )", sql.strip()):
        op.execute(statement)


def install_guards() -> None:
    _execute("""
    CREATE FUNCTION fp_service_state(j jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
      SELECT (j-ARRAY['created_at','updated_at','ended_at']) || CASE WHEN j ? 'ended_at' THEN jsonb_build_object('ended_at',extract(epoch FROM (j->>'ended_at')::timestamptz)) ELSE '{}'::jsonb END
    $$;
    CREATE FUNCTION fp_service_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Service evidence is append-only'; END $$;
    CREATE FUNCTION fp_service_state_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE visit fp_service_visits; resource fp_tables;
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Service context history cannot be deleted'; END IF;
      PERFORM 1 FROM fp_venues WHERE id=NEW.venue_id FOR NO KEY UPDATE;
      IF TG_OP='INSERT' THEN
        IF NEW.version IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'Initial service version must be one'; END IF;
      ELSE
        IF NEW.id IS DISTINCT FROM OLD.id OR NEW.venue_id IS DISTINCT FROM OLD.venue_id OR NEW.created_at IS DISTINCT FROM OLD.created_at OR NEW.version IS DISTINCT FROM OLD.version+1 OR NEW.last_command_id IS NOT DISTINCT FROM OLD.last_command_id THEN RAISE EXCEPTION 'Service revision requires a new command'; END IF;
      END IF;
      IF TG_TABLE_NAME='fp_service_visits' THEN
        IF NEW.reservation_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM fp_reservations WHERE id=NEW.reservation_id AND venue_id=NEW.venue_id) THEN RAISE EXCEPTION 'Reservation scope differs'; END IF;
        IF TG_OP='UPDATE' THEN
          IF NEW.number IS DISTINCT FROM OLD.number OR NEW.reservation_id IS DISTINCT FROM OLD.reservation_id OR OLD.ended_at IS NOT NULL THEN RAISE EXCEPTION 'Visit origin or ended visit is immutable'; END IF;
        ELSIF NEW.ended_at IS NOT NULL THEN RAISE EXCEPTION 'Visit must begin present'; END IF;
      ELSIF TG_TABLE_NAME='fp_guest_tabs' THEN
        SELECT * INTO visit FROM fp_service_visits WHERE id=NEW.visit_id AND venue_id=NEW.venue_id;
        IF visit.id IS NULL OR (visit.ended_at IS NOT NULL AND (NEW.present OR NEW.last_command_id IS DISTINCT FROM visit.last_command_id)) THEN RAISE EXCEPTION 'Inactive or foreign guest visit'; END IF;
        IF TG_OP='UPDATE' THEN
          IF NEW.visit_id IS DISTINCT FROM OLD.visit_id OR NEW.kind IS DISTINCT FROM OLD.kind OR NEW.number IS DISTINCT FROM OLD.number THEN RAISE EXCEPTION 'Guest identity cannot be reassigned'; END IF;
        END IF;
        IF NEW.current_table_id IS NOT NULL THEN
          SELECT * INTO resource FROM fp_tables WHERE id=NEW.current_table_id AND venue_id=NEW.venue_id FOR UPDATE;
          IF resource.id IS NULL OR resource.kind!='table' THEN RAISE EXCEPTION 'Guest table scope differs'; END IF;
          IF NEW.present AND NEW.kind='guest' THEN
            IF (SELECT count(*) FROM fp_guest_tabs t JOIN fp_service_visits v ON v.id=t.visit_id WHERE t.venue_id=NEW.venue_id AND t.current_table_id=resource.id AND t.present AND t.kind='guest' AND v.ended_at IS NULL AND t.id!=NEW.id)>=resource.seats THEN RAISE EXCEPTION 'Guest table capacity exceeded'; END IF;
            IF length(NEW.seat_label)>0 AND EXISTS(SELECT 1 FROM fp_guest_tabs t JOIN fp_service_visits v ON v.id=t.visit_id WHERE t.venue_id=NEW.venue_id AND t.current_table_id=resource.id AND t.present AND t.kind='guest' AND v.ended_at IS NULL AND t.id!=NEW.id AND lower(t.seat_label)=lower(NEW.seat_label)) THEN RAISE EXCEPTION 'Guest seat is already occupied'; END IF;
          END IF;
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE FUNCTION fp_service_command_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE role text;
    BEGIN
      SELECT m.role INTO role FROM fp_memberships m JOIN users u ON u.id=m.user_id JOIN fp_venues v ON v.id=m.venue_id WHERE m.venue_id=NEW.venue_id AND m.user_id=NEW.actor_id AND m.active AND u.is_active AND u.tenant_id=v.tenant_id;
      IF role IS NULL OR role NOT IN ('manager','service') OR (NEW.kind='settings' AND role!='manager') OR NEW.request_hash !~ '^[0-9a-f]{64}$' OR NEW.kind NOT IN ('settings','visit_created','tab_created','tab_context','visit_ended','round_created','units_assigned') OR jsonb_typeof(NEW.snapshots) IS DISTINCT FROM 'array' OR jsonb_typeof(NEW.result) IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'Invalid scoped service command'; END IF;
      IF NEW.kind IN ('tab_context','visit_ended','units_assigned') AND length(trim(NEW.reason))<3 THEN RAISE EXCEPTION 'Service correction reason required'; END IF;
      RETURN NEW;
    END $$;
    CREATE FUNCTION fp_service_require_command() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE command fp_service_commands; entry jsonb;
    BEGIN
      SELECT * INTO command FROM fp_service_commands WHERE id=NEW.last_command_id AND venue_id=NEW.venue_id;
      SELECT value INTO entry FROM jsonb_array_elements(command.snapshots) WHERE value->>'entity'=TG_TABLE_NAME AND value->'state'->>'id'=NEW.id::text;
      IF command.id IS NULL OR entry IS NULL OR NOT(entry ?& ARRAY['state','before']) OR fp_service_state(entry->'state') IS DISTINCT FROM fp_service_state(to_jsonb(NEW)) THEN RAISE EXCEPTION 'Service context requires matching immutable command'; END IF;
      IF TG_TABLE_NAME='fp_service_settings' THEN
        IF command.kind IS DISTINCT FROM 'settings' OR command.target_id IS DISTINCT FROM NEW.venue_id THEN RAISE EXCEPTION 'Settings require the manager settings command'; END IF;
      ELSIF TG_TABLE_NAME='fp_service_visits' THEN
        IF TG_OP='INSERT' THEN
          IF command.kind IS DISTINCT FROM 'visit_created' OR command.target_id IS DISTINCT FROM NEW.venue_id THEN RAISE EXCEPTION 'Visit creation command differs'; END IF;
        ELSE
          IF command.kind NOT IN ('tab_created','round_created','visit_ended') OR command.target_id IS DISTINCT FROM NEW.id OR ((NEW.ended_at IS DISTINCT FROM OLD.ended_at) IS DISTINCT FROM (command.kind='visit_ended')) THEN RAISE EXCEPTION 'Visit revision command differs'; END IF;
        END IF;
      ELSIF TG_TABLE_NAME='fp_guest_tabs' THEN
        IF TG_OP='INSERT' THEN
          IF NOT ((command.kind='visit_created' AND command.target_id=NEW.venue_id) OR (command.kind='tab_created' AND command.target_id=NEW.visit_id)) THEN RAISE EXCEPTION 'Guest creation command differs'; END IF;
        ELSE
          IF NOT ((command.kind='tab_context' AND command.target_id=NEW.id) OR (command.kind='visit_ended' AND command.target_id=NEW.visit_id AND NOT NEW.present)) THEN RAISE EXCEPTION 'Guest revision command differs'; END IF;
        END IF;
      END IF;
      IF TG_OP='INSERT' THEN
        IF entry->'before' IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'Initial service command has no predecessor'; END IF;
      ELSE
        IF fp_service_state(entry->'before') IS DISTINCT FROM fp_service_state(to_jsonb(OLD)) THEN RAISE EXCEPTION 'Service predecessor differs'; END IF;
      END IF;
      IF TG_TABLE_NAME='fp_service_visits' THEN
        IF NEW.ended_at IS NOT NULL AND EXISTS(SELECT 1 FROM fp_guest_tabs WHERE visit_id=NEW.id AND present) THEN RAISE EXCEPTION 'Ended visit must end every personal presence'; END IF;
      END IF;
      RETURN NEW;
    END $$;
    """)
    for table in STATE_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_state_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION fp_service_state_guard()"
        )
        op.execute(
            f"CREATE CONSTRAINT TRIGGER {table}_require_command AFTER INSERT OR UPDATE ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fp_service_require_command()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION fp_service_immutable()"
        )
    for table in APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION fp_service_immutable()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION fp_service_immutable()"
        )
    op.execute(
        "CREATE TRIGGER fp_service_commands_scope BEFORE INSERT ON fp_service_commands FOR EACH ROW EXECUTE FUNCTION fp_service_command_guard()"
    )
    _round_guards()


def _round_guards() -> None:
    _execute("""
    CREATE FUNCTION fp_service_assignment_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE bill fp_orders; tab fp_guest_tabs; prior fp_service_unit_assignments; item jsonb; quantity integer;
    BEGIN
      PERFORM 1 FROM fp_venues WHERE id=NEW.venue_id FOR NO KEY UPDATE;
      SELECT * INTO bill FROM fp_orders WHERE id=NEW.order_id AND venue_id=NEW.venue_id FOR UPDATE;
      SELECT * INTO tab FROM fp_guest_tabs WHERE id=NEW.guest_tab_id AND venue_id=NEW.venue_id;
      IF bill.id IS NULL OR tab.id IS NULL OR EXISTS(SELECT 1 FROM fp_service_visits WHERE id=tab.visit_id AND ended_at IS NOT NULL) THEN RAISE EXCEPTION 'Assignment must use own active visit and original receipt'; END IF;
      SELECT l INTO item FROM jsonb_array_elements(bill.lines) WITH ORDINALITY AS x(l,ordinal) WHERE fp_cash_line_id(bill.id,ordinal-1,l)=NEW.line_id::text;
      IF item IS NULL OR jsonb_typeof(item->'quantity') IS DISTINCT FROM 'number' THEN RAISE EXCEPTION 'Original service unit is absent'; END IF;
      quantity:=(item->>'quantity')::integer;
      IF NEW.unit<0 OR NEW.unit>=quantity THEN RAISE EXCEPTION 'Original service unit index invalid'; END IF;
      SELECT * INTO prior FROM fp_service_unit_assignments WHERE order_id=bill.id AND line_id=NEW.line_id AND unit=NEW.unit ORDER BY version DESC LIMIT 1;
      IF NEW.version IS DISTINCT FROM coalesce(prior.version,0)+1 OR NEW.before_tab_id IS DISTINCT FROM prior.guest_tab_id OR (prior.id IS NOT NULL AND NEW.guest_tab_id=prior.guest_tab_id) THEN RAISE EXCEPTION 'Assignment revision or predecessor differs'; END IF;
      IF prior.id IS NOT NULL AND ROW(NEW.cart_row_id,NEW.cart_unit) IS DISTINCT FROM ROW(prior.cart_row_id,prior.cart_unit) THEN RAISE EXCEPTION 'Original cart provenance cannot change'; END IF;
      IF EXISTS(SELECT 1 FROM fp_service_unit_assignments a JOIN fp_guest_tabs t ON t.id=a.guest_tab_id WHERE a.order_id=bill.id AND t.visit_id!=tab.visit_id) THEN RAISE EXCEPTION 'One original belongs to one visit'; END IF;
      IF bill.pos_requested OR bill.paid_at IS NOT NULL OR bill.voucher_cents>0 OR EXISTS(SELECT 1 FROM fp_cancellation_units u WHERE u.order_id=bill.id AND u.line_id=NEW.line_id AND u.unit=NEW.unit) OR EXISTS(SELECT 1 FROM fp_cash_entries e CROSS JOIN LATERAL jsonb_array_elements(e.allocations) a WHERE e.order_id=bill.id AND e.kind='sale' AND a->>'line_id'=NEW.line_id::text AND (a->>'unit')::integer=NEW.unit AND (a->>'amount_cents')::integer>0) THEN RAISE EXCEPTION 'Financially bound or cancelled units cannot be reassigned'; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER fp_service_assignments_scope BEFORE INSERT ON fp_service_unit_assignments FOR EACH ROW EXECUTE FUNCTION fp_service_assignment_guard();
    CREATE FUNCTION fp_service_evidence_complete() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE command fp_service_commands; round_ fp_service_rounds; child fp_service_round_children; tab fp_guest_tabs; bill fp_orders; expected jsonb; actual jsonb; needed integer; entry jsonb;
    BEGIN
      IF TG_TABLE_NAME='fp_service_rounds' THEN
        SELECT * INTO round_ FROM fp_service_rounds WHERE id=NEW.id;
      ELSIF TG_TABLE_NAME='fp_service_round_children' THEN
        SELECT * INTO round_ FROM fp_service_rounds WHERE id=NEW.round_id;
      ELSIF TG_TABLE_NAME='fp_service_unit_assignments' THEN
        SELECT * INTO command FROM fp_service_commands WHERE id=NEW.command_id AND venue_id=NEW.venue_id;
        IF command.id IS NULL OR command.kind NOT IN ('round_created','units_assigned') THEN RAISE EXCEPTION 'Assignment requires its immutable command'; END IF;
        IF command.kind='units_assigned' THEN
          SELECT a INTO entry FROM jsonb_array_elements(command.result->'assignments') a WHERE a->>'id'=NEW.id::text;
          IF entry IS NULL OR entry->>'order_id' IS DISTINCT FROM NEW.order_id::text OR entry->>'line_id' IS DISTINCT FROM NEW.line_id::text OR (entry->>'unit')::integer IS DISTINCT FROM NEW.unit OR entry->>'guest_tab_id' IS DISTINCT FROM NEW.guest_tab_id::text OR (entry->>'version')::integer IS DISTINCT FROM NEW.version THEN RAISE EXCEPTION 'Assignment result differs'; END IF;
          RETURN NEW;
        END IF;
        SELECT r.* INTO round_ FROM fp_service_rounds r JOIN fp_service_round_children c ON c.round_id=r.id WHERE c.order_id=NEW.order_id;
        IF round_.command_id IS DISTINCT FROM NEW.command_id OR NEW.cart_row_id IS NULL OR NEW.cart_unit IS NULL THEN RAISE EXCEPTION 'Round assignment origin differs'; END IF;
      ELSE
        IF NEW.kind='round_created' THEN SELECT * INTO round_ FROM fp_service_rounds WHERE command_id=NEW.id;
        ELSIF NEW.kind='units_assigned' THEN
          IF jsonb_typeof(NEW.result->'assignments') IS DISTINCT FROM 'array' OR jsonb_array_length(NEW.result->'assignments')<1 OR (SELECT count(*) FROM fp_service_unit_assignments WHERE command_id=NEW.id) IS DISTINCT FROM jsonb_array_length(NEW.result->'assignments')::bigint THEN RAISE EXCEPTION 'Assignment command requires all units'; END IF;
          RETURN NEW;
        ELSE RETURN NEW; END IF;
      END IF;
      IF round_.id IS NULL THEN RAISE EXCEPTION 'Round evidence missing'; END IF;
      SELECT * INTO command FROM fp_service_commands WHERE id=round_.command_id AND venue_id=round_.venue_id;
      IF command.id IS NULL OR command.kind!='round_created' OR command.target_id IS DISTINCT FROM round_.visit_id OR command.result->>'id' IS DISTINCT FROM round_.id::text THEN RAISE EXCEPTION 'Round command differs'; END IF;
      IF jsonb_typeof(round_.expected_tab_ids) IS DISTINCT FROM 'array' OR jsonb_array_length(round_.expected_tab_ids)<1 THEN RAISE EXCEPTION 'Round children cannot be empty'; END IF;
      SELECT jsonb_agg(value ORDER BY value) INTO expected FROM jsonb_array_elements(round_.expected_tab_ids);
      SELECT jsonb_agg(to_jsonb(guest_tab_id::text) ORDER BY guest_tab_id::text) INTO actual FROM fp_service_round_children WHERE round_id=round_.id;
      IF expected IS DISTINCT FROM actual OR (SELECT count(DISTINCT value) FROM jsonb_array_elements(round_.expected_tab_ids)) IS DISTINCT FROM jsonb_array_length(round_.expected_tab_ids)::bigint THEN RAISE EXCEPTION 'Round requires its exact complete child set'; END IF;
      FOR child IN SELECT * FROM fp_service_round_children WHERE round_id=round_.id LOOP
        SELECT * INTO tab FROM fp_guest_tabs WHERE id=child.guest_tab_id;
        SELECT * INTO bill FROM fp_orders WHERE id=child.order_id;
        IF tab.visit_id IS DISTINCT FROM round_.visit_id OR child.venue_id IS DISTINCT FROM round_.venue_id OR bill.venue_id IS DISTINCT FROM round_.venue_id OR bill.actor_id IS DISTINCT FROM command.actor_id OR bill.request_key IS DISTINCT FROM public.uuid_generate_v5(command.request_key,tab.id::text) THEN RAISE EXCEPTION 'Round child source or identity differs'; END IF;
        SELECT c INTO entry FROM jsonb_array_elements(command.result->'children') c WHERE c->>'order_id'=bill.id::text;
        IF entry IS NULL OR entry->>'guest_tab_id' IS DISTINCT FROM tab.id::text OR entry->>'number' IS DISTINCT FROM bill.number THEN RAISE EXCEPTION 'Round child result absent'; END IF;
        SELECT sum((l->>'quantity')::integer) INTO needed FROM jsonb_array_elements(bill.lines) l;
        IF needed IS NULL OR needed<1 OR (SELECT count(*) FROM fp_service_unit_assignments WHERE order_id=bill.id AND command_id=command.id AND guest_tab_id=tab.id AND version=1) IS DISTINCT FROM needed::bigint THEN RAISE EXCEPTION 'Round requires original-unit assignment completeness'; END IF;
      END LOOP;
      RETURN NEW;
    END $$;
    CREATE FUNCTION fp_service_order_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF EXISTS(SELECT 1 FROM fp_service_unit_assignments WHERE order_id=OLD.id) THEN
        IF ROW(NEW.table_id,NEW.customer_id,NEW.guests,NEW.currency,NEW.fulfillment,NEW.subtotal_cents,NEW.actor_id,NEW.device_id,NEW.request_key,NEW.request_hash,NEW.number)
          IS DISTINCT FROM ROW(OLD.table_id,OLD.customer_id,OLD.guests,OLD.currency,OLD.fulfillment,OLD.subtotal_cents,OLD.actor_id,OLD.device_id,OLD.request_key,OLD.request_hash,OLD.number) OR
          (SELECT jsonb_agg(l-ARRAY['preparation_status','discount_cents','total_cents','tax_cents'] ORDER BY n) FROM jsonb_array_elements(NEW.lines) WITH ORDINALITY x(l,n))
          IS DISTINCT FROM (SELECT jsonb_agg(l-ARRAY['preparation_status','discount_cents','total_cents','tax_cents'] ORDER BY n) FROM jsonb_array_elements(OLD.lines) WITH ORDINALITY x(l,n)) THEN RAISE EXCEPTION 'Guest service keeps original unit sources and placement snapshots'; END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER fp_orders_service_original BEFORE UPDATE ON fp_orders FOR EACH ROW EXECUTE FUNCTION fp_service_order_guard();
    CREATE FUNCTION fp_service_discount_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NOT EXISTS(SELECT 1 FROM fp_service_unit_assignments WHERE order_id=OLD.id) THEN RETURN NEW; END IF;
      IF ROW(NEW.total_cents,NEW.discount_cents,NEW.discount_reason,(SELECT jsonb_agg(l- 'preparation_status' ORDER BY n) FROM jsonb_array_elements(NEW.lines) WITH ORDINALITY x(l,n)))
        IS NOT DISTINCT FROM ROW(OLD.total_cents,OLD.discount_cents,OLD.discount_reason,(SELECT jsonb_agg(l-'preparation_status' ORDER BY n) FROM jsonb_array_elements(OLD.lines) WITH ORDINALITY x(l,n))) THEN RETURN NEW; END IF;
      IF OLD.pos_requested OR OLD.paid_at IS NOT NULL OR EXISTS(SELECT 1 FROM fp_cancellation_units WHERE order_id=OLD.id) THEN RAISE EXCEPTION 'Financially locked original cannot be discounted'; END IF;
      IF NEW.version IS DISTINCT FROM OLD.version+1 OR NOT EXISTS(SELECT 1 FROM fp_events e JOIN fp_memberships m ON m.user_id=e.actor_id AND m.venue_id=e.venue_id JOIN users u ON u.id=e.actor_id JOIN fp_venues v ON v.id=e.venue_id WHERE e.venue_id=NEW.venue_id AND e.aggregate_id=NEW.id AND e.kind='order.discounted' AND m.active AND m.role='manager' AND u.is_active AND u.tenant_id=v.tenant_id AND (e.payload->>'version')::integer=NEW.version AND (e.payload->>'discount_cents')::integer=NEW.discount_cents AND trim(e.payload->>'reason')=NEW.discount_reason AND length(trim(e.payload->>'reason'))>=3) THEN RAISE EXCEPTION 'Guest receipt discount requires its exact manager event'; END IF;
      RETURN NEW;
    END $$;
    CREATE CONSTRAINT TRIGGER fp_orders_service_discount AFTER UPDATE ON fp_orders DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fp_service_discount_evidence();
    CREATE FUNCTION fp_service_table_capacity() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.seats<(SELECT count(*) FROM fp_guest_tabs t JOIN fp_service_visits v ON v.id=t.visit_id WHERE t.current_table_id=NEW.id AND t.present AND t.kind='guest' AND v.ended_at IS NULL) THEN RAISE EXCEPTION 'Table has more present guests than proposed capacity'; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER fp_tables_service_capacity BEFORE UPDATE ON fp_tables FOR EACH ROW EXECUTE FUNCTION fp_service_table_capacity();
    """)
    for table in APPEND_ONLY:
        op.execute(
            f"CREATE CONSTRAINT TRIGGER {table}_complete AFTER INSERT ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fp_service_evidence_complete()"
        )


def downgrade() -> None:
    for table in (*APPEND_ONLY, *STATE_TABLES):
        if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM {table})")).scalar_one():
            raise RuntimeError("Downgrade would erase immutable guest service evidence")
    op.execute("DROP TRIGGER fp_orders_service_original ON fp_orders")
    op.execute("DROP TRIGGER fp_orders_service_discount ON fp_orders")
    op.execute("DROP TRIGGER fp_tables_service_capacity ON fp_tables")
    for table in (
        "fp_service_unit_assignments",
        "fp_service_round_children",
        "fp_service_rounds",
        "fp_guest_tabs",
        "fp_service_visits",
        "fp_service_settings",
        "fp_service_commands",
    ):
        op.drop_table(table)
    for name in (
        "fp_service_table_capacity()",
        "fp_service_discount_evidence()",
        "fp_service_order_guard()",
        "fp_service_evidence_complete()",
        "fp_service_assignment_guard()",
        "fp_service_require_command()",
        "fp_service_command_guard()",
        "fp_service_state_guard()",
        "fp_service_immutable()",
        "fp_service_state(jsonb)",
    ):
        op.execute("DROP FUNCTION " + name)
