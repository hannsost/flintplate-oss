"""Immutable, sourced personnel cost schedules with guarded UTC validity."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "080"
down_revision = "079"
branch_labels = None
depends_on = None


def install_guards(bind: sa.Connection) -> None:
    bind.exec_driver_sql(r"""
      CREATE FUNCTION fp_guard_labour_rate_revision() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE tenant uuid; venue_currency text; latest_id uuid; latest_version integer;
              period jsonb; period_start timestamptz; period_end timestamptz;
              previous_end timestamptz; had_previous boolean := false;
      BEGIN
        IF TG_OP <> 'INSERT' THEN
          RAISE EXCEPTION 'Personnel calculation rate evidence is immutable';
        END IF;
        SELECT tenant_id,currency INTO tenant,venue_currency FROM fp_venues
          WHERE id=NEW.venue_id FOR UPDATE;
        IF NOT EXISTS(SELECT 1 FROM users u JOIN fp_memberships m ON m.user_id=u.id
          WHERE u.id=NEW.worker_id AND u.tenant_id=tenant AND m.venue_id=NEW.venue_id)
          OR NEW.currency IS DISTINCT FROM venue_currency THEN
          RAISE EXCEPTION 'Personnel rate scope or currency is inconsistent';
        END IF;
        SELECT id,version INTO latest_id,latest_version FROM fp_labour_rate_revisions
          WHERE venue_id=NEW.venue_id AND worker_id=NEW.worker_id ORDER BY version DESC LIMIT 1;
        IF NEW.version IS DISTINCT FROM coalesce(latest_version,0)+1
          OR NEW.previous_id IS DISTINCT FROM latest_id THEN
          RAISE EXCEPTION 'Personnel rate revision does not continue the latest evidence';
        END IF;
        FOR period IN SELECT value FROM jsonb_array_elements(NEW.periods) LOOP
          IF jsonb_typeof(period) IS DISTINCT FROM 'object'
             OR NOT (period ?& ARRAY['valid_from','valid_until','hourly_cents','employer_markup_bps','source_reference'])
             OR (SELECT count(*) FROM jsonb_object_keys(period)) <> 5 THEN
            RAISE EXCEPTION 'Personnel rate period is incomplete';
          END IF;
          IF jsonb_typeof(period->'valid_from') IS DISTINCT FROM 'string'
             OR period->>'valid_from' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T.*(Z|[+-][0-9]{2}:[0-9]{2})$'
             OR jsonb_typeof(period->'valid_until') NOT IN ('string','null') THEN
            RAISE EXCEPTION 'Personnel rate validity requires explicit timezone';
          END IF;
          IF jsonb_typeof(period->'valid_until')='string'
             AND period->>'valid_until' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T.*(Z|[+-][0-9]{2}:[0-9]{2})$' THEN
            RAISE EXCEPTION 'Personnel rate validity end requires explicit timezone';
          END IF;
          IF jsonb_typeof(period->'hourly_cents') IS DISTINCT FROM 'number'
             OR jsonb_typeof(period->'employer_markup_bps') IS DISTINCT FROM 'number'
             OR period->>'hourly_cents' !~ '^[0-9]+$'
             OR period->>'employer_markup_bps' !~ '^[0-9]+$'
             OR (period->>'hourly_cents')::numeric > 1000000
             OR (period->>'employer_markup_bps')::numeric > 100000
             OR jsonb_typeof(period->'source_reference') IS DISTINCT FROM 'string'
             OR length(btrim(period->>'source_reference')) NOT BETWEEN 3 AND 300 THEN
            RAISE EXCEPTION 'Personnel rate amount or source is invalid';
          END IF;
          period_start := (period->>'valid_from')::timestamptz;
          period_end := (period->>'valid_until')::timestamptz;
          IF period_end <= period_start
             OR (had_previous AND (previous_end IS NULL OR period_start < previous_end)) THEN
            RAISE EXCEPTION 'Personnel rate validity periods overlap or are not ordered';
          END IF;
          previous_end := period_end;
          had_previous := true;
        END LOOP;
        RETURN NEW;
      END $$
    """)
    bind.exec_driver_sql(
        "CREATE TRIGGER fp_labour_rate_revision_guard BEFORE INSERT OR UPDATE OR DELETE "
        "ON fp_labour_rate_revisions FOR EACH ROW EXECUTE FUNCTION fp_guard_labour_rate_revision()"
    )
    bind.exec_driver_sql(
        "CREATE TRIGGER fp_labour_rate_revision_no_truncate BEFORE TRUNCATE "
        "ON fp_labour_rate_revisions FOR EACH STATEMENT EXECUTE FUNCTION fp_guard_labour_rate_revision()"
    )


def upgrade() -> None:
    op.create_table(
        "fp_labour_rate_revisions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("worker_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("previous_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("request_key", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("source_reference", sa.String(300), nullable=False),
        sa.Column("periods", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("venue_id", "worker_id", "id", name="uq_fp_labour_revision_scope"),
        sa.UniqueConstraint(
            "venue_id", "worker_id", "version", name="uq_fp_labour_revision_version"
        ),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_labour_revision_request"),
        sa.ForeignKeyConstraint(
            ["venue_id", "worker_id", "previous_id"],
            [
                "fp_labour_rate_revisions.venue_id",
                "fp_labour_rate_revisions.worker_id",
                "fp_labour_rate_revisions.id",
            ],
            name="fk_fp_labour_revision_previous",
        ),
        sa.CheckConstraint(
            "version > 0 AND ((version = 1) = (previous_id IS NULL))",
            name="ck_fp_labour_revision_version",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(periods) = 'array' AND jsonb_array_length(periods) <= 200",
            name="ck_fp_labour_revision_periods",
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) BETWEEN 3 AND 300 AND length(btrim(source_reference)) BETWEEN 3 AND 300",
            name="ck_fp_labour_revision_source",
        ),
    )
    op.create_index(
        "ix_fp_labour_rate_revisions_venue_id", "fp_labour_rate_revisions", ["venue_id"]
    )
    op.create_index(
        "ix_fp_labour_rate_revisions_worker_id", "fp_labour_rate_revisions", ["worker_id"]
    )
    install_guards(op.get_bind())


def downgrade() -> None:
    # Keep usable historical evidence until an explicit backup/restore plan is
    # chosen; an application downgrade must not erase personnel rate history.
    op.execute("""
      DO $$ BEGIN IF EXISTS(SELECT 1 FROM fp_labour_rate_revisions) THEN
        RAISE EXCEPTION 'Personnel rate evidence requires an explicit restore plan before downgrade';
      END IF; END $$
    """)
    op.execute("DROP TRIGGER fp_labour_rate_revision_no_truncate ON fp_labour_rate_revisions")
    op.execute("DROP TRIGGER fp_labour_rate_revision_guard ON fp_labour_rate_revisions")
    op.execute("DROP FUNCTION fp_guard_labour_rate_revision()")
    op.drop_table("fp_labour_rate_revisions")
