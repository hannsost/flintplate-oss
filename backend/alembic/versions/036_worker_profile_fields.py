"""036 worker_profile_fields – Add personal contact fields to worker_settings

Revision ID: 036
Revises: 035
Create Date: 2026-03-27
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("worker_settings", sa.Column("phone", sa.String(50), nullable=True))
    op.add_column("worker_settings", sa.Column("address_street", sa.String(300), nullable=True))
    op.add_column("worker_settings", sa.Column("address_city", sa.String(100), nullable=True))
    op.add_column("worker_settings", sa.Column("address_zip", sa.String(20), nullable=True))
    op.add_column(
        "worker_settings",
        sa.Column("address_country", sa.String(100), nullable=True, server_default="DE"),
    )
    op.add_column("worker_settings", sa.Column("date_of_birth", sa.Date, nullable=True))
    op.add_column(
        "worker_settings", sa.Column("emergency_contact_name", sa.String(200), nullable=True)
    )
    op.add_column(
        "worker_settings", sa.Column("emergency_contact_phone", sa.String(50), nullable=True)
    )
    op.add_column("worker_settings", sa.Column("iban", sa.String(34), nullable=True))
    op.add_column("worker_settings", sa.Column("avatar_url", sa.String(1000), nullable=True))


def downgrade() -> None:
    for col in [
        "phone",
        "address_street",
        "address_city",
        "address_zip",
        "address_country",
        "date_of_birth",
        "emergency_contact_name",
        "emergency_contact_phone",
        "iban",
        "avatar_url",
    ]:
        op.drop_column("worker_settings", col)
