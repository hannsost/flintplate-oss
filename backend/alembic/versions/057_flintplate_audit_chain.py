"""Append-only event journal with venue-local hash chain and ordered cursors."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fp_events", sa.Column("audit_sequence", sa.BigInteger(), nullable=True))
    op.add_column("fp_events", sa.Column("previous_hash", sa.String(64), nullable=True))
    op.add_column("fp_events", sa.Column("event_hash", sa.String(64), nullable=True))
    op.add_column("fp_events", sa.Column("canonical_payload", sa.Text(), nullable=True))
    for statement in (
        "CREATE FUNCTION fp_event_canonical(e fp_events) RETURNS text LANGUAGE SQL IMMUTABLE AS $$\n      SELECT jsonb_build_object('id',e.id,'venue_id',e.venue_id,'sequence',e.sequence,\n        'audit_sequence',e.audit_sequence,'kind',e.kind,'aggregate_id',e.aggregate_id,\n        'actor_id',e.actor_id,'device_id',e.device_id,'payload',e.payload,\n        'created_at_epoch',extract(epoch from e.created_at))::text\n    $$",
        "DO $$ DECLARE r fp_events; prev text; n bigint; BEGIN\n      FOR r IN SELECT * FROM fp_events ORDER BY sequence LOOP\n        SELECT event_hash,audit_sequence INTO prev,n FROM fp_events\n          WHERE venue_id=r.venue_id AND audit_sequence IS NOT NULL ORDER BY audit_sequence DESC LIMIT 1;\n        r.audit_sequence=coalesce(n,0)+1;\n        r.previous_hash=coalesce(prev,repeat('0',64));\n        r.canonical_payload=fp_event_canonical(r);\n        r.event_hash=encode(sha256(convert_to(r.previous_hash || '|' || r.canonical_payload,'UTF8')),'hex');\n        UPDATE fp_events SET audit_sequence=r.audit_sequence,previous_hash=r.previous_hash,\n          canonical_payload=r.canonical_payload,event_hash=r.event_hash WHERE id=r.id;\n      END LOOP;\n    END $$",
        "CREATE FUNCTION fp_seal_event() RETURNS trigger LANGUAGE plpgsql AS $$\n    DECLARE prev text; n bigint; BEGIN\n      PERFORM pg_advisory_xact_lock(hashtextextended(NEW.venue_id::text,777));\n      SELECT event_hash,audit_sequence INTO prev,n FROM fp_events WHERE venue_id=NEW.venue_id\n        ORDER BY audit_sequence DESC LIMIT 1;\n      NEW.audit_sequence=coalesce(n,0)+1;\n      NEW.previous_hash=coalesce(prev,repeat('0',64));\n      -- Allocate after acquiring the venue lock. A polling adapter cannot skip\n      -- an uncommitted earlier event from this venue after advancing its cursor.\n      NEW.sequence=nextval(pg_get_serial_sequence('fp_events','sequence'));\n      NEW.canonical_payload=fp_event_canonical(NEW);\n      NEW.event_hash=encode(sha256(convert_to(NEW.previous_hash || '|' || NEW.canonical_payload,'UTF8')),'hex');\n      RETURN NEW;\n    END $$",
        "CREATE TRIGGER fp_events_seal BEFORE INSERT ON fp_events FOR EACH ROW EXECUTE FUNCTION fp_seal_event()",
        "CREATE FUNCTION fp_reject_journal_mutation() RETURNS trigger LANGUAGE plpgsql AS $$\n    BEGIN RAISE EXCEPTION 'FlintPlate journal is append-only; record a compensating event'; END $$",
        "CREATE TRIGGER fp_events_immutable BEFORE UPDATE OR DELETE ON fp_events\n      FOR EACH ROW EXECUTE FUNCTION fp_reject_journal_mutation()",
        "CREATE TRIGGER fp_events_no_truncate BEFORE TRUNCATE ON fp_events\n      FOR EACH STATEMENT EXECUTE FUNCTION fp_reject_journal_mutation()",
    ):
        op.execute(statement)
    op.create_unique_constraint("uq_fp_audit_sequence", "fp_events", ["venue_id", "audit_sequence"])
    # Nullable only for metadata-only unit-test databases and legacy ingest; the
    # production insert trigger always fills all fields. No application writes them.


def downgrade() -> None:
    for statement in (
        "DROP TRIGGER fp_events_no_truncate ON fp_events",
        "DROP TRIGGER fp_events_immutable ON fp_events",
        "DROP TRIGGER fp_events_seal ON fp_events",
        "DROP FUNCTION fp_reject_journal_mutation()",
        "DROP FUNCTION fp_seal_event()",
        "DROP FUNCTION fp_event_canonical(fp_events)",
    ):
        op.execute(statement)
    op.drop_constraint("uq_fp_audit_sequence", "fp_events", type_="unique")
    for column in ("canonical_payload", "event_hash", "previous_hash", "audit_sequence"):
        op.drop_column("fp_events", column)
