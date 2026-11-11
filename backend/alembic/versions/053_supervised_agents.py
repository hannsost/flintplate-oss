"""Separate agent identities, versioned capabilities and reviewed task assignments.

Downgrading removes agent runs and agent-only tasks; human tasks are preserved.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def uid(
    name: str,
    target: str,
    *,
    nullable: bool = False,
    ondelete: str = "RESTRICT",
    unique: bool = False,
) -> sa.Column:
    return sa.Column(
        name,
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
        unique=unique,
    )


def stamp() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


def pk() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True)


def upgrade() -> None:
    op.create_table(
        "agents",
        pk(),
        uid("tenant_id", "customers.id", ondelete="CASCADE"),
        sa.Column("name", sa.String(120), nullable=False),
        uid("owner_id", "users.id", nullable=True, ondelete="SET NULL"),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        stamp(),
    )
    op.create_index("ix_agents_tenant_id", "agents", ["tenant_id"])
    op.create_table(
        "agent_versions",
        pk(),
        uid("agent_id", "agents.id", ondelete="CASCADE"),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("capability", sa.String(40), nullable=False),
        sa.Column("daily_task_limit", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("four_eyes", sa.Boolean(), nullable=False),
        uid("created_by", "users.id", nullable=True, ondelete="SET NULL"),
        stamp(),
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_version"),
    )
    op.create_index("ix_agent_versions_agent_id", "agent_versions", ["agent_id"])
    op.alter_column("tasks", "assigned_to", nullable=True)
    op.add_column("tasks", uid("assigned_agent_id", "agents.id", nullable=True))
    op.create_index("ix_tasks_assigned_agent_id", "tasks", ["assigned_agent_id"])
    op.create_check_constraint(
        "ck_task_one_assignee",
        "tasks",
        "(assigned_to IS NOT NULL) <> (assigned_agent_id IS NOT NULL)",
    )
    op.create_table(
        "agent_runs",
        pk(),
        uid("tenant_id", "customers.id", ondelete="CASCADE"),
        uid("agent_id", "agents.id"),
        uid("agent_version_id", "agent_versions.id"),
        uid("task_id", "tasks.id", unique=True),
        uid("work_item_id", "work_items.id", unique=True),
        uid("job_id", "job_postings.id"),
        sa.Column("job_version", sa.Integer(), nullable=False),
        uid("delegated_by", "users.id", nullable=True, ondelete="SET NULL"),
        sa.Column("delegated_auth_version", sa.Integer(), nullable=False),
        sa.Column("owner_auth_version", sa.Integer(), nullable=False),
        uid("reviewer_id", "users.id", nullable=True, ondelete="SET NULL"),
        sa.Column("reviewer_auth_version", sa.Integer(), nullable=False),
        sa.Column("request_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("source", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("output", sa.Text()),
        sa.Column("output_origin", sa.String(40)),
        sa.Column("provider_model", sa.String(250)),
        sa.Column("review_note", sa.String(2000)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        stamp(),
        sa.UniqueConstraint("tenant_id", "request_key", name="uq_agent_run_request"),
    )
    op.create_index("ix_agent_runs_tenant_id", "agent_runs", ["tenant_id"])
    op.create_table(
        "agent_events",
        pk(),
        uid("run_id", "agent_runs.id", ondelete="CASCADE"),
        uid("actor_id", "users.id", nullable=True, ondelete="SET NULL"),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("run_version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("run_id", "run_version", name="uq_agent_event_version"),
        stamp(),
    )
    op.create_index("ix_agent_events_run_id", "agent_events", ["run_id"])


def downgrade() -> None:
    op.drop_table("agent_events")
    op.drop_table("agent_runs")
    op.execute("DELETE FROM tasks WHERE assigned_agent_id IS NOT NULL")
    op.drop_constraint("ck_task_one_assignee", "tasks", type_="check")
    op.drop_index("ix_tasks_assigned_agent_id", table_name="tasks")
    op.drop_column("tasks", "assigned_agent_id")
    op.alter_column("tasks", "assigned_to", nullable=False)
    op.drop_table("agent_versions")
    op.drop_table("agents")
