"""Configured stations and immutable command evidence; never rewrite old orders."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "078"
down_revision = "077"
branch_labels = None
depends_on = None


def base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def install_guards(bind: sa.Connection) -> None:
    bind.exec_driver_sql("""
      CREATE FUNCTION fp_station_identity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP<>'UPDATE' THEN RAISE EXCEPTION 'Operating stations cannot be deleted or truncated'; END IF;
        IF ROW(NEW.id,NEW.venue_id,NEW.code,NEW.kind,NEW.created_at)
          IS DISTINCT FROM ROW(OLD.id,OLD.venue_id,OLD.code,OLD.kind,OLD.created_at) THEN
          RAISE EXCEPTION 'Station identity and work classification are immutable';
        END IF;
        RETURN NEW;
      END $$
    """)
    bind.exec_driver_sql(
        "CREATE TRIGGER fp_station_identity BEFORE UPDATE OR DELETE ON fp_operating_stations FOR EACH ROW EXECUTE FUNCTION fp_station_identity_guard()"
    )
    bind.exec_driver_sql(
        "CREATE TRIGGER fp_station_no_truncate BEFORE TRUNCATE ON fp_operating_stations FOR EACH STATEMENT EXECUTE FUNCTION fp_station_identity_guard()"
    )
    bind.exec_driver_sql("""
      CREATE FUNCTION fp_station_command_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'Station command evidence is append-only'; END $$
    """)
    bind.exec_driver_sql(
        "CREATE TRIGGER fp_station_command_no_mutation BEFORE UPDATE OR DELETE ON fp_station_commands FOR EACH ROW EXECUTE FUNCTION fp_station_command_immutable()"
    )
    bind.exec_driver_sql(
        "CREATE TRIGGER fp_station_command_no_truncate BEFORE TRUNCATE ON fp_station_commands FOR EACH STATEMENT EXECUTE FUNCTION fp_station_command_immutable()"
    )


def upgrade() -> None:
    op.create_table(
        "fp_operating_stations",
        *base_columns(),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("venue_id", "code", name="uq_fp_station_code"),
        sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]{0,39}$'", name="ck_fp_station_code"),
        sa.CheckConstraint(
            "kind IN ('kitchen','bar','service','activities')", name="ck_fp_station_kind"
        ),
        sa.CheckConstraint(
            "version > 0 AND sort_order BETWEEN 0 AND 999", name="ck_fp_station_version"
        ),
        sa.CheckConstraint("length(btrim(name)) BETWEEN 2 AND 80", name="ck_fp_station_name"),
    )
    op.create_index("ix_fp_operating_stations_venue_id", "fp_operating_stations", ["venue_id"])
    op.create_index(
        "uq_fp_station_name",
        "fp_operating_stations",
        ["venue_id", sa.text("lower(name)")],
        unique=True,
    )
    op.execute("""
      INSERT INTO fp_operating_stations(id,venue_id,code,name,kind,sort_order)
      SELECT gen_random_uuid(),v.id,s.code,s.name,s.kind,s.sort_order FROM fp_venues v CROSS JOIN
      (VALUES ('kitchen','Küche','kitchen',10),('bar','Bar','bar',20),
              ('service','Service','service',30),('activities','Aktivitäten','activities',40))
      AS s(code,name,kind,sort_order)
    """)
    op.create_table(
        "fp_station_commands",
        *base_columns(),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("request_key", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("result", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_station_command"),
    )
    op.create_index("ix_fp_station_commands_venue_id", "fp_station_commands", ["venue_id"])
    install_guards(op.get_bind())


def downgrade() -> None:
    # Earlier application schemas cannot interpret custom routing. Never fix
    # that incompatibility by rewriting paid order evidence during a downgrade.
    op.execute("""
      DO $$ BEGIN
        IF EXISTS(SELECT 1 FROM fp_menu_items WHERE coalesce(draft->>'station','kitchen') NOT IN ('kitchen','bar')
          OR (published IS NOT NULL AND coalesce(published->>'station','kitchen') NOT IN ('kitchen','bar')))
          OR EXISTS(SELECT 1 FROM fp_orders o CROSS JOIN LATERAL jsonb_array_elements(o.lines) l
             WHERE coalesce(l->>'kind','product')='product' AND coalesce(l->>'station','kitchen') NOT IN ('kitchen','bar'))
          OR EXISTS(SELECT 1 FROM fp_shifts s JOIN fp_operating_stations st ON st.venue_id=s.venue_id AND st.code=s.station
             WHERE st.code NOT IN ('kitchen','bar','service','activities')) THEN
          RAISE EXCEPTION 'Custom station references require an explicit restore plan before downgrade';
        END IF;
      END $$
    """)
    op.execute("DROP TRIGGER fp_station_command_no_truncate ON fp_station_commands")
    op.execute("DROP TRIGGER fp_station_command_no_mutation ON fp_station_commands")
    op.execute("DROP FUNCTION fp_station_command_immutable()")
    op.execute("DROP TRIGGER fp_station_no_truncate ON fp_operating_stations")
    op.execute("DROP TRIGGER fp_station_identity ON fp_operating_stations")
    op.execute("DROP FUNCTION fp_station_identity_guard()")
    op.drop_table("fp_station_commands")
    op.drop_table("fp_operating_stations")
