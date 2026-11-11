"""Encrypted per-venue FireFlint sessions and transferred snapshot."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fp_fireflint_links", sa.Column("access_ciphertext", sa.String(24000)))
    op.add_column("fp_fireflint_links", sa.Column("refresh_ciphertext", sa.String(24000)))
    op.add_column("fp_fireflint_links", sa.Column("snapshot_data", pg.JSONB()))


def downgrade() -> None:
    for name in ("snapshot_data", "refresh_ciphertext", "access_ciphertext"):
        op.drop_column("fp_fireflint_links", name)
