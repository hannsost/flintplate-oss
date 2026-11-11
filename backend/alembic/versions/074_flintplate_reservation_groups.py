"""One reservation across linked tables, explicit waitlist and service receipts."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "074"
down_revision = "073"
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


def upgrade() -> None:
    op.create_table(
        "fp_reservation_meta",
        *base_columns(),
        sa.Column(
            "reservation_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("fp_reservations.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("source", sa.String(20), nullable=False, server_default="reservation"),
        sa.Column("note", sa.String(500), nullable=False, server_default=""),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_fp_reservation_meta_reservation_id", "fp_reservation_meta", ["reservation_id"]
    )
    op.create_table(
        "fp_reservation_resources",
        *base_columns(),
        sa.Column(
            "reservation_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("fp_reservations.id"),
            nullable=False,
        ),
        sa.Column("table_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_tables.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("reservation_id", "table_id", name="uq_fp_reservation_resource"),
        sa.UniqueConstraint("reservation_id", "position", name="uq_fp_reservation_position"),
        sa.CheckConstraint("position BETWEEN 0 AND 7", name="ck_fp_reservation_position"),
    )
    for field in ("reservation_id", "table_id"):
        op.create_index(f"ix_fp_reservation_resources_{field}", "fp_reservation_resources", [field])
    op.execute("""
        INSERT INTO fp_reservation_resources(id,reservation_id,table_id,position)
        SELECT gen_random_uuid(),id,table_id,0 FROM fp_reservations
    """)
    op.create_table(
        "fp_waitlist_entries",
        *base_columns(),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("guest_name", sa.String(120), nullable=False),
        sa.Column("guests", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(500), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="waiting"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "reservation_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("fp_reservations.id"),
            nullable=True,
            unique=True,
        ),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("guests BETWEEN 1 AND 100", name="ck_fp_waitlist_guests"),
        sa.CheckConstraint(
            "status IN ('waiting','seated','cancelled')", name="ck_fp_waitlist_status"
        ),
        sa.CheckConstraint(
            "(status = 'seated') = (reservation_id IS NOT NULL)", name="ck_fp_waitlist_seated"
        ),
    )
    op.create_index("ix_fp_waitlist_entries_venue_id", "fp_waitlist_entries", ["venue_id"])
    op.create_table(
        "fp_reservation_commands",
        *base_columns(),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("request_key", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("result", pg.JSONB(), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_reservation_command"),
    )
    op.create_index("ix_fp_reservation_commands_venue_id", "fp_reservation_commands", ["venue_id"])
    op.execute("""
      CREATE FUNCTION fp_reject_reservation_evidence_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'Reservation resource and command evidence is append-only'; END $$
    """)
    for name in ("fp_reservation_resources", "fp_reservation_commands"):
        op.execute(
            f"CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION fp_reject_reservation_evidence_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {name}_no_truncate BEFORE TRUNCATE ON {name} FOR EACH STATEMENT EXECUTE FUNCTION fp_reject_reservation_evidence_mutation()"
        )
    op.execute("""
      CREATE FUNCTION fp_check_reservation_resource_scope() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE venue uuid; resource_venue uuid; primary_table uuid;
      BEGIN
        SELECT venue_id,table_id INTO venue,primary_table FROM fp_reservations WHERE id=NEW.reservation_id;
        SELECT venue_id INTO resource_venue FROM fp_tables WHERE id=NEW.table_id;
        IF venue IS NULL OR venue IS DISTINCT FROM resource_venue OR (NEW.position=0 AND NEW.table_id IS DISTINCT FROM primary_table) THEN
          RAISE EXCEPTION 'Reservation resource scope mismatch';
        END IF;
        RETURN NEW;
      END $$
    """)
    op.execute(
        "CREATE TRIGGER fp_reservation_resource_scope BEFORE INSERT ON fp_reservation_resources FOR EACH ROW EXECUTE FUNCTION fp_check_reservation_resource_scope()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER fp_reservation_resource_scope ON fp_reservation_resources")
    op.execute("DROP FUNCTION fp_check_reservation_resource_scope()")
    for name in ("fp_reservation_commands", "fp_reservation_resources"):
        op.execute(f"DROP TRIGGER {name}_no_truncate ON {name}")
        op.execute(f"DROP TRIGGER {name}_immutable ON {name}")
    op.execute("DROP FUNCTION fp_reject_reservation_evidence_mutation()")
    for name in (
        "fp_reservation_commands",
        "fp_waitlist_entries",
        "fp_reservation_resources",
        "fp_reservation_meta",
    ):
        op.drop_table(name)
