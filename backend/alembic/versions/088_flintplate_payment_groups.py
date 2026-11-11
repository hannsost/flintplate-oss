"""Atomic original-unit cash groups, persistent splits and additive tip evidence.

Revision ID: 088
Revises: 087
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op
from tools.payment_group_migration import install_guards, remove_guards

revision = "088"
down_revision = "087"
branch_labels = None
depends_on = None


def base() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("venue_id", sa.Uuid(), sa.ForeignKey("fp_venues.id"), nullable=False),
    ]


def ref(
    name: str, target: str, *, nullable: bool = False, unique: bool = False
) -> sa.Column[object]:
    return sa.Column(name, sa.Uuid(), sa.ForeignKey(target), nullable=nullable, unique=unique)


def number(name: str) -> sa.Column[object]:
    return sa.Column(name, sa.Integer(), nullable=False)


def string(name: str, length: int) -> sa.Column[object]:
    return sa.Column(name, sa.String(length), nullable=False)


def json_column(name: str) -> sa.Column[object]:
    return sa.Column(name, JSONB(), nullable=False)


def command() -> list[sa.Column[object]]:
    return [sa.Column("request_key", sa.Uuid(), nullable=False), string("request_hash", 64)]


def upgrade() -> None:
    op.create_table(
        "fp_payment_groups",
        *base(),
        ref("session_id", "fp_cash_sessions.id"),
        ref("actor_id", "users.id"),
        ref("payer_tab_id", "fp_guest_tabs.id", nullable=True),
        string("payer_label", 80),
        string("currency", 3),
        number("receipt_amount_cents"),
        number("new_tip_cents"),
        number("amount_cents"),
        number("received_cents"),
        number("change_cents"),
        *command(),
        string("quote_hash", 64),
        string("source_hash", 64),
        json_column("source_snapshot"),
        json_column("quote"),
        json_column("allocations"),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_payment_group_request"),
        sa.CheckConstraint(
            "receipt_amount_cents>=0 AND new_tip_cents>=0 AND amount_cents=receipt_amount_cents+new_tip_cents AND amount_cents>0 AND received_cents>=amount_cents AND change_cents=received_cents-amount_cents",
            name="ck_fp_payment_group_amounts",
        ),
    )
    op.create_table(
        "fp_payment_group_entries",
        *base(),
        ref("group_id", "fp_payment_groups.id"),
        ref("order_id", "fp_orders.id"),
        ref("entry_id", "fp_cash_entries.id", unique=True),
        sa.UniqueConstraint("group_id", "order_id", name="uq_fp_payment_group_order"),
    )
    op.create_table(
        "fp_payer_tip_entries",
        *base(),
        ref("payment_group_id", "fp_payment_groups.id"),
        ref("session_id", "fp_cash_sessions.id"),
        ref("original_id", "fp_payer_tip_entries.id", nullable=True),
        string("kind", 20),
        number("amount_cents"),
        string("currency", 3),
        ref("actor_id", "users.id"),
        ref("payer_tab_id", "fp_guest_tabs.id", nullable=True),
        string("payer_label", 80),
        ref("recipient_id", "users.id", nullable=True),
        *command(),
        string("reason", 300),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_payer_tip_request"),
        sa.CheckConstraint(
            "(kind='received' AND amount_cents>0 AND original_id IS NULL) OR (kind='returned' AND amount_cents<0 AND original_id IS NOT NULL)",
            name="ck_fp_payer_tip_sign",
        ),
    )
    op.create_index(
        "uq_fp_payer_tip_group",
        "fp_payer_tip_entries",
        ["payment_group_id"],
        unique=True,
        postgresql_where=sa.text("kind='received'"),
    )
    op.create_table(
        "fp_tip_run_sources",
        *base(),
        ref("run_id", "fp_tip_runs.id"),
        string("kind", 20),
        ref("order_id", "fp_orders.id", nullable=True, unique=True),
        ref("payer_tip_id", "fp_payer_tip_entries.id", nullable=True, unique=True),
        number("amount_cents"),
        string("source_hash", 64),
        json_column("source_snapshot"),
        sa.CheckConstraint(
            "amount_cents>0 AND ((kind='order' AND order_id IS NOT NULL AND payer_tip_id IS NULL) OR (kind='payer_tip' AND order_id IS NULL AND payer_tip_id IS NOT NULL))",
            name="ck_fp_tip_run_source",
        ),
    )
    op.create_table(
        "fp_equal_split_plans",
        *base(),
        sa.Column(
            "root_plan_id",
            sa.Uuid(),
            sa.ForeignKey("fp_equal_split_plans.id", deferrable=True, initially="DEFERRED"),
            nullable=False,
        ),
        ref("supersedes_id", "fp_equal_split_plans.id", nullable=True, unique=True),
        number("revision"),
        ref("actor_id", "users.id"),
        *command(),
        string("currency", 3),
        number("total_cents"),
        string("source_hash", 64),
        json_column("source_snapshot"),
        json_column("selection"),
        string("reason", 300),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_equal_plan_request"),
        sa.UniqueConstraint("root_plan_id", "revision", name="uq_fp_equal_plan_revision"),
        sa.CheckConstraint("revision>0 AND total_cents>0", name="ck_fp_equal_plan_amount"),
    )
    op.create_table(
        "fp_equal_split_parts",
        *base(),
        ref("plan_id", "fp_equal_split_plans.id"),
        number("ordinal"),
        ref("payer_tab_id", "fp_guest_tabs.id", nullable=True),
        string("label", 80),
        number("target_cents"),
        json_column("unit_budgets"),
        sa.UniqueConstraint("plan_id", "ordinal", name="uq_fp_equal_part_ordinal"),
        sa.CheckConstraint("ordinal>=0 AND target_cents>=0", name="ck_fp_equal_part_amount"),
    )
    op.create_table(
        "fp_equal_split_part_payments",
        *base(),
        ref("group_id", "fp_payment_groups.id"),
        ref("part_id", "fp_equal_split_parts.id"),
        number("amount_cents"),
        json_column("allocations"),
        sa.UniqueConstraint("group_id", "part_id", name="uq_fp_equal_part_group"),
        sa.CheckConstraint("amount_cents>0", name="ck_fp_equal_part_payment_amount"),
    )
    op.create_table(
        "fp_equal_split_plan_actions",
        *base(),
        ref("plan_id", "fp_equal_split_plans.id", unique=True),
        ref("next_plan_id", "fp_equal_split_plans.id", nullable=True, unique=True),
        ref("actor_id", "users.id"),
        string("action", 20),
        string("reason", 300),
        *command(),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_equal_action_request"),
    )
    indexes = {
        "fp_payment_groups": ["session_id"],
        "fp_payment_group_entries": ["group_id"],
        "fp_payer_tip_entries": ["payment_group_id", "session_id", "original_id"],
        "fp_tip_run_sources": ["run_id"],
        "fp_equal_split_plans": [],
        "fp_equal_split_parts": ["plan_id"],
        "fp_equal_split_part_payments": ["group_id", "part_id"],
        "fp_equal_split_plan_actions": [],
    }
    for table, columns in indexes.items():
        for column in ["id", "venue_id", *columns]:
            op.create_index(f"ix_{table}_{column}", table, [column])
    install_guards()


def downgrade() -> None:
    remove_guards()
    for table in (
        "fp_equal_split_plan_actions",
        "fp_equal_split_part_payments",
        "fp_equal_split_parts",
        "fp_equal_split_plans",
        "fp_tip_run_sources",
        "fp_payer_tip_entries",
        "fp_payment_group_entries",
        "fp_payment_groups",
    ):
        op.drop_table(table)
