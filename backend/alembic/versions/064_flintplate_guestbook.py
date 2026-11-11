"""Guest book: profiles for regulars and dated notes with a visibility scope."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fp_venues",
        sa.Column("guestbook_retention_days", sa.Integer(), nullable=False, server_default="365"),
    )
    op.create_check_constraint(
        "ck_fp_venue_retention",
        "fp_venues",
        "guestbook_retention_days BETWEEN 30 AND 1095",
    )
    op.create_table(
        "fp_guest_profiles",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("reference", sa.String(160), nullable=False, server_default=""),
        # Day and month only: enough to congratulate, not a full date of birth.
        sa.Column("birthday", sa.String(5), nullable=True),
        sa.Column(
            "account_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("fp_guest_accounts.id"),
            nullable=True,
        ),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        # Consent for notes that touch health, diet or belief. Without it they are refused.
        sa.Column("consent_special", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_fp_guest_profiles_venue_id", "fp_guest_profiles", ["venue_id"])
    op.create_table(
        "fp_guest_notes",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "profile_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("fp_guest_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("author_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("text", sa.String(1000), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="team"),
        sa.Column("sensitive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("visibility IN ('team','private')", name="ck_fp_note_visibility"),
    )
    op.create_index("ix_fp_guest_notes_profile_id", "fp_guest_notes", ["profile_id"])
    op.create_index("ix_fp_guest_notes_expires_at", "fp_guest_notes", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_fp_guest_notes_expires_at", table_name="fp_guest_notes")
    op.drop_index("ix_fp_guest_notes_profile_id", table_name="fp_guest_notes")
    op.drop_table("fp_guest_notes")
    op.drop_index("ix_fp_guest_profiles_venue_id", table_name="fp_guest_profiles")
    op.drop_table("fp_guest_profiles")
    op.drop_constraint("ck_fp_venue_retention", "fp_venues", type_="check")
    op.drop_column("fp_venues", "guestbook_retention_days")
