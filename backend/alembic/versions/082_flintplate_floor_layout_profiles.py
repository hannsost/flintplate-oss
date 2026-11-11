"""Named floor arrangements with immutable revisions and command recovery."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "082"
down_revision = "081"
branch_labels = None
depends_on = None


def base_columns() -> list[sa.Column[object]]:
    # GastroBase overrides BOTH timestamps as timezone-aware DateTime.
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


def install_guards() -> None:
    op.execute("""
    CREATE FUNCTION fp_floor_layout_profile_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='INSERT' THEN
        IF NEW.version<>1 OR NEW.archived THEN RAISE EXCEPTION 'New layout profiles start active at version1'; END IF;
        IF NEW.room_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM fp_rooms r WHERE r.id=NEW.room_id AND r.venue_id=NEW.venue_id) THEN
          RAISE EXCEPTION 'Layout room belongs to another venue or is missing';
        END IF;
        RETURN NEW;
      END IF;
      IF TG_OP<>'UPDATE' THEN RAISE EXCEPTION 'Floor layout profiles cannot be deleted or truncated'; END IF;
      IF (to_jsonb(NEW)-ARRAY['name','archived','version','updated_at']) IS DISTINCT FROM
         (to_jsonb(OLD)-ARRAY['name','archived','version','updated_at']) OR NEW.version<>OLD.version+1 THEN
        RAISE EXCEPTION 'Layout profile identity is immutable; state requires the next version';
      END IF;
      IF NOT EXISTS(SELECT 1 FROM fp_floor_layout_revisions r WHERE r.venue_id=NEW.venue_id AND r.profile_id=NEW.id
        AND r.version=NEW.version AND r.name=NEW.name AND r.archived=NEW.archived AND r.room_id IS NOT DISTINCT FROM NEW.room_id) THEN
        RAISE EXCEPTION 'Layout metadata requires its immutable matching revision';
      END IF;
      RETURN NEW;
    END $$
    """)
    op.execute("""
    CREATE FUNCTION fp_floor_layout_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE p fp_floor_layout_profiles%ROWTYPE;
    BEGIN
      IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Floor layout revision evidence is append-only'; END IF;
      SELECT * INTO p FROM fp_floor_layout_profiles WHERE id=NEW.profile_id AND venue_id=NEW.venue_id FOR UPDATE;
      IF NOT FOUND OR p.room_id IS DISTINCT FROM NEW.room_id THEN RAISE EXCEPTION 'Layout revision scope does not match its profile'; END IF;
      IF NEW.version=1 THEN
        IF p.version<>1 OR NEW.previous_id IS NOT NULL OR NEW.name<>p.name OR NEW.archived<>p.archived THEN
          RAISE EXCEPTION 'Initial layout revision does not match its profile';
        END IF;
      ELSIF NEW.version<>p.version+1 OR NOT EXISTS(SELECT 1 FROM fp_floor_layout_revisions r WHERE r.id=NEW.previous_id
         AND r.venue_id=NEW.venue_id AND r.profile_id=NEW.profile_id AND r.version=p.version) THEN
        RAISE EXCEPTION 'Layout revision must follow the current profile version';
      END IF;
      RETURN NEW;
    END $$
    """)
    op.execute("""
    CREATE FUNCTION fp_floor_layout_command_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Floor layout command evidence is append-only'; END $$
    """)
    for table, operation, function in (
        ("fp_floor_layout_profiles", "INSERT OR UPDATE OR DELETE", "fp_floor_layout_profile_guard"),
        (
            "fp_floor_layout_revisions",
            "INSERT OR UPDATE OR DELETE",
            "fp_floor_layout_revision_guard",
        ),
        ("fp_floor_layout_commands", "UPDATE OR DELETE", "fp_floor_layout_command_guard"),
    ):
        op.execute(
            f"CREATE TRIGGER {table}_guard BEFORE {operation} ON {table} FOR EACH ROW EXECUTE FUNCTION {function}()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION {function}()"
        )
    # A two-step ORM append then head update is valid within one transaction.
    # Neither an empty head nor an orphan future revision may survive COMMIT.
    op.execute("""
    CREATE FUNCTION fp_floor_layout_head_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE p fp_floor_layout_profiles%ROWTYPE;
            r fp_floor_layout_revisions%ROWTYPE;
            target_id uuid;
    BEGIN
      IF TG_TABLE_NAME='fp_floor_layout_profiles' THEN target_id := NEW.id;
      ELSE target_id := NEW.profile_id; END IF;
      SELECT * INTO p FROM fp_floor_layout_profiles WHERE id=target_id AND venue_id=NEW.venue_id;
      IF NOT FOUND THEN RAISE EXCEPTION 'Layout profile head is missing'; END IF;
      SELECT * INTO r FROM fp_floor_layout_revisions WHERE profile_id=p.id AND venue_id=p.venue_id
        ORDER BY version DESC LIMIT 1;
      IF NOT FOUND OR r.version<>p.version OR r.name<>p.name OR r.archived<>p.archived
        OR r.room_id IS DISTINCT FROM p.room_id THEN
        RAISE EXCEPTION 'Layout profile head requires its latest matching revision at commit';
      END IF;
      RETURN NEW;
    END $$
    """)
    for table, operation in (
        ("fp_floor_layout_profiles", "INSERT OR UPDATE"),
        ("fp_floor_layout_revisions", "INSERT"),
    ):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER {table}_head AFTER {operation} ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fp_floor_layout_head_guard()"
        )


def upgrade() -> None:
    op.create_table(
        "fp_floor_layout_profiles",
        *base_columns(),
        sa.Column("name", sa.String(80), nullable=False),
        # Historical scope does not prevent later room removal. Capturing and
        # applying validate that every referenced room belongs to this venue.
        sa.Column("room_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_floor_layout_profile_scope"),
        sa.CheckConstraint(
            "version > 0 AND length(btrim(name)) BETWEEN 2 AND 80",
            name="ck_fp_floor_layout_profile_state",
        ),
    )
    op.create_index(
        "uq_fp_floor_layout_profile_name",
        "fp_floor_layout_profiles",
        ["venue_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("NOT archived"),
    )
    op.create_table(
        "fp_floor_layout_revisions",
        *base_columns(),
        sa.Column("profile_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("previous_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("room_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("placements", pg.JSONB(), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.UniqueConstraint(
            "venue_id", "profile_id", "id", name="uq_fp_floor_layout_revision_scope"
        ),
        sa.UniqueConstraint("profile_id", "version", name="uq_fp_floor_layout_revision_version"),
        sa.ForeignKeyConstraint(
            ["venue_id", "profile_id"],
            ["fp_floor_layout_profiles.venue_id", "fp_floor_layout_profiles.id"],
            name="fk_fp_floor_layout_revision_profile",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id", "profile_id", "previous_id"],
            [
                "fp_floor_layout_revisions.venue_id",
                "fp_floor_layout_revisions.profile_id",
                "fp_floor_layout_revisions.id",
            ],
            name="fk_fp_floor_layout_revision_previous",
        ),
        sa.CheckConstraint(
            "(version = 1 AND previous_id IS NULL) OR (version > 1 AND previous_id IS NOT NULL)",
            name="ck_fp_floor_layout_revision_previous",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(placements) = 'array' AND jsonb_array_length(placements) BETWEEN 1 AND 500",
            name="ck_fp_floor_layout_revision_placements",
        ),
    )
    op.create_table(
        "fp_floor_layout_commands",
        *base_columns(),
        sa.Column("request_key", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("result", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_floor_layout_command_request"),
        sa.CheckConstraint(
            "kind IN ('position','save','apply','archive')", name="ck_fp_floor_layout_command_kind"
        ),
    )
    for table in (
        "fp_floor_layout_profiles",
        "fp_floor_layout_revisions",
        "fp_floor_layout_commands",
    ):
        op.create_index(f"ix_{table}_venue_id", table, ["venue_id"])
    op.create_index(
        "ix_fp_floor_layout_revisions_profile_id", "fp_floor_layout_revisions", ["profile_id"]
    )
    install_guards()


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM fp_floor_layout_profiles) OR EXISTS(SELECT 1 FROM fp_floor_layout_revisions)
         OR EXISTS(SELECT 1 FROM fp_floor_layout_commands) THEN
        RAISE EXCEPTION '082 downgrade would erase floor layout history';
      END IF;
    END $$""")
    for table in (
        "fp_floor_layout_commands",
        "fp_floor_layout_revisions",
        "fp_floor_layout_profiles",
    ):
        op.execute(f"DROP TRIGGER {table}_guard ON {table}")
        op.execute(f"DROP TRIGGER {table}_no_truncate ON {table}")
    for table in ("fp_floor_layout_revisions", "fp_floor_layout_profiles"):
        op.execute(f"DROP TRIGGER {table}_head ON {table}")
    for function in (
        "fp_floor_layout_head_guard",
        "fp_floor_layout_command_guard",
        "fp_floor_layout_revision_guard",
        "fp_floor_layout_profile_guard",
    ):
        op.execute(f"DROP FUNCTION {function}()")
    for table in (
        "fp_floor_layout_commands",
        "fp_floor_layout_revisions",
        "fp_floor_layout_profiles",
    ):
        op.drop_table(table)
