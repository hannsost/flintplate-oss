"""Reviewed offers and onboarding without duplicate person records."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def identity() -> list[sa.Column]:  # Alembic's schema API uses generic columns.
    return [
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    ]


def reference(name: str, target: str, *, nullable: bool = False, unique: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.UUID(),
        sa.ForeignKey(target, ondelete="SET NULL" if nullable else "CASCADE"),
        nullable=nullable,
        unique=unique,
    )


def upgrade() -> None:
    op.create_table(
        "hiring_offers",
        *identity(),
        reference("tenant_id", "customers.id"),
        reference("application_id", "applications.id"),
        reference("created_by", "users.id", nullable=True),
        reference("approver_id", "users.id", nullable=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("terms", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("shared_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_hiring_offers_tenant_id", "hiring_offers", ["tenant_id"])
    op.create_index("ix_hiring_offers_application_id", "hiring_offers", ["application_id"])
    op.create_index(
        "uq_hiring_offer_active_application",
        "hiring_offers",
        ["application_id"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('declined', 'withdrawn')"),
    )
    op.create_table(
        "offer_events",
        *identity(),
        reference("offer_id", "hiring_offers.id"),
        reference("actor_id", "users.id", nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(2000)),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("terms", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=False),
    )
    op.create_index("ix_offer_events_offer_id", "offer_events", ["offer_id"])
    op.create_table(
        "onboarding_cases",
        *identity(),
        reference("tenant_id", "customers.id"),
        reference("offer_id", "hiring_offers.id", unique=True),
        reference("person_id", "users.id"),
        reference("owner_id", "users.id", nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("template", sa.String(50), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_onboarding_cases_tenant_id", "onboarding_cases", ["tenant_id"])
    op.create_index("ix_onboarding_cases_person_id", "onboarding_cases", ["person_id"])
    op.create_table(
        "onboarding_steps",
        *identity(),
        reference("case_id", "onboarding_cases.id"),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("audience", sa.String(20), nullable=False),
        reference("assignee_id", "users.id", nullable=True),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        reference("completed_by", "users.id", nullable=True),
    )
    op.create_index("ix_onboarding_steps_case_id", "onboarding_steps", ["case_id"])


def downgrade() -> None:
    op.drop_index("ix_onboarding_steps_case_id", table_name="onboarding_steps")
    op.drop_table("onboarding_steps")
    op.drop_index("ix_onboarding_cases_person_id", table_name="onboarding_cases")
    op.drop_index("ix_onboarding_cases_tenant_id", table_name="onboarding_cases")
    op.drop_table("onboarding_cases")
    op.drop_index("ix_offer_events_offer_id", table_name="offer_events")
    op.drop_table("offer_events")
    op.drop_index("ix_hiring_offers_tenant_id", table_name="hiring_offers")
    op.drop_index("uq_hiring_offer_active_application", table_name="hiring_offers")
    op.drop_index("ix_hiring_offers_application_id", table_name="hiring_offers")
    op.drop_table("hiring_offers")
