"""Explicit availability and atomic staff replacement requests."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None


def uid(
    name: str, target: str | None = None, nullable: bool = False, unique: bool = False
) -> sa.Column:
    return sa.Column(
        name,
        pg.UUID(as_uuid=True),
        *([sa.ForeignKey(target)] if target else []),
        nullable=nullable,
        unique=unique,
    )


def table(name: str, *columns: sa.SchemaItem) -> None:
    op.create_table(
        name,
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        *columns,
    )


def upgrade() -> None:
    op.add_column(
        "fp_memberships",
        sa.Column("stations", pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "fp_memberships", sa.Column("competence", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        "fp_memberships",
        sa.Column("emergency_opt_in", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    table(
        "fp_availability",
        uid("venue_id", "fp_venues.id"),
        uid("worker_id", "users.id"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ends_at > starts_at", name="ck_fp_available_interval"),
    )
    table(
        "fp_emergencies",
        uid("venue_id", "fp_venues.id"),
        uid("shift_id", "fp_shifts.id"),
        uid("replacement_shift_id", "fp_shifts.id", True),
        uid("actor_id", "users.id"),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("timeout_minutes", sa.Integer(), nullable=False),
        sa.Column("ranking", pg.JSONB(), nullable=False),
        uid("request_key", unique=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_index(
        "uq_fp_open_replacement",
        "fp_emergencies",
        ["shift_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    table(
        "fp_emergency_offers",
        uid("emergency_id", "fp_emergencies.id"),
        uid("worker_id", "users.id"),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("emergency_id", "worker_id", name="uq_fp_emergency_worker"),
    )
    for name, columns in {
        "fp_availability": ["venue_id", "worker_id"],
        "fp_emergencies": ["venue_id", "shift_id"],
        "fp_emergency_offers": ["emergency_id", "worker_id"],
    }.items():
        op.create_index(f"ix_{name}_id", name, ["id"])
        for column in columns:
            op.create_index(f"ix_{name}_{column}", name, [column])


def downgrade() -> None:
    for name in ("fp_emergency_offers", "fp_emergencies", "fp_availability"):
        op.drop_table(name)
    for name in ("stations", "competence", "emergency_opt_in"):
        op.drop_column("fp_memberships", name)
