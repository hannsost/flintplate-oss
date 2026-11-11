"""033 equipment – Equipment items and worker assignments

Revision ID: 033
Revises: 032
Create Date: 2026-03-27
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None

EQUIPMENT_STATUSES = ("available", "assigned", "maintenance", "retired")
EQUIPMENT_CONDITIONS = ("new", "good", "fair", "poor")
EQUIPMENT_CATEGORIES = ("laptop", "phone", "vehicle", "tools", "clothing", "other")


def upgrade() -> None:
    op.create_table(
        "equipment_items",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(50), nullable=False, server_default="other"),
        sa.Column("serial_number", sa.String(100), nullable=True),
        sa.Column("asset_tag", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="available"),
        sa.Column("condition", sa.String(20), nullable=False, server_default="good"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_equipment_items_tenant_id", "equipment_items", ["tenant_id"])
    op.create_index("ix_equipment_items_status", "equipment_items", ["status"])

    op.create_table(
        "equipment_assignments",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "equipment_item_id",
            UUID(as_uuid=True),
            sa.ForeignKey("equipment_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "worker_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assigned_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("assigned_at", sa.Date, nullable=False),
        sa.Column("returned_at", sa.Date, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_equipment_assignments_worker_id", "equipment_assignments", ["worker_id"])
    op.create_index(
        "ix_equipment_assignments_item_id", "equipment_assignments", ["equipment_item_id"]
    )
    op.create_index("ix_equipment_assignments_tenant_id", "equipment_assignments", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("equipment_assignments")
    op.drop_table("equipment_items")
